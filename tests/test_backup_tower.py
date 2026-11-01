"""The nightly off-machine backup (vigild/backup.py `run_nightly`): build, verify, ship to a
remote, verify the remote, retain 14 days, record an event, and show on /api/health. The
"remote" is a local temp dir; the ssh transport is a fake."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth
from vigild import backup
from vigild.db import Store, iso
from vigild.gitsafe import git
from vigild.services import Services, Tokens

NOW = datetime(2026, 10, 31, 3, 15, 0, tzinfo=UTC)
STAMP = "20261031T031500Z"


def LocalRemote(root: Path) -> backup.RsyncRemote:
    """The remote is a local directory: real rsync, no ssh (the -e option is ignored)."""
    root.mkdir(parents=True, exist_ok=True)
    r = backup.RsyncRemote(f"{root}/")
    r.root_path = root  # type: ignore[attr-defined]
    return r


def _names(r: backup.RsyncRemote) -> list[str]:
    return sorted(p.name for p in r.root_path.iterdir())  # type: ignore[attr-defined]


def _bare_repo(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    git(path.parent, "init", "--quiet", "--bare", str(path))


@pytest.fixture(autouse=True)
def _local_rsync(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test-only: this Mac's rsync is openrsync; skip the production GNU check."""
    monkeypatch.setattr(backup, "_TEST_SKIP_RSYNC_CHECK", True)


@pytest.fixture
def data(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    (root / "vault").mkdir(parents=True)
    _bare_repo(root / "vault" / "o" / "r.git")
    (root / "vault" / "blob").write_text("hello")
    (root / "coord").mkdir()
    (root / "coord" / "notes.md").write_text("keep")
    (root / "coord" / "brief.md").write_text("keep too")
    (root / "coord" / "run.pid").write_text("1")
    (root / "coord" / "x.tmp").write_text("t")
    (root / "coord" / "sub" / "__pycache__").mkdir(parents=True)
    (root / "coord" / "sub" / "__pycache__" / "m.pyc").write_text("c")
    (root / "coord" / "sub" / "deep.tmp").write_text("t")
    (root / "coord" / "sub" / "real.txt").write_text("r")
    store = Store.open(root / "vigil.db")
    store.conn.close()
    return root


def _events(data: Path) -> list[dict[str, object]]:
    import json

    s = Store.open(data / "vigil.db")
    try:
        return [json.loads(r["data"]) for r in s.q("SELECT data FROM events WHERE type='backup'")]
    finally:
        s.conn.close()


def _run(
    data: Path, tmp_path: Path, remote: backup.RsyncRemote, **kw: object
) -> backup.NightlyResult:
    return backup.run_nightly(
        data,
        tmp_path / "local",
        remote,
        now=kw.pop("now", NOW),
        **kw,  # type: ignore[arg-type]
    )


def test_run_builds_verifies_ships_and_records(data: Path, tmp_path: Path) -> None:
    remote = LocalRemote(tmp_path / "remote")
    res = _run(data, tmp_path, remote)
    assert res.ok and res.stamp == STAMP
    local = tmp_path / "local"
    assert (local / f"vigil-{STAMP}.db").is_file()
    assert (local / f"vigil-{STAMP}.vault" / "o" / "r.git" / "HEAD").is_file()
    assert (local / f"vigil-{STAMP}.coord" / "notes.md").read_text() == "keep"
    shipped = tmp_path / "remote" / STAMP
    assert (shipped / "vigil.db").is_file()
    assert (shipped / "vault" / "o" / "r.git" / "HEAD").is_file()
    assert (shipped / "coord" / "brief.md").is_file()
    assert backup._ours(shipped / backup.REMOTE_MARKER)
    [ev] = _events(data)
    assert ev["ok"] is True and ev["stamp"] == STAMP
    assert ev["remote"] == f"{tmp_path / 'remote'}/"
    assert ev["integrity"] == "ok" and ev["fsck"] == {"repos": 1, "failed": []}
    assert ev["remote_verified"] is True and ev["retention_removed"] == []
    sizes = ev["sizes"]
    assert isinstance(sizes, dict) and sizes["db"] > 0 and "vault" in sizes and "coord" in sizes
    assert isinstance(ev["duration_s"], (int, float))


def test_coord_transient_files_are_excluded(data: Path, tmp_path: Path) -> None:
    _run(data, tmp_path, LocalRemote(tmp_path / "remote"))
    for base in (
        tmp_path / "local" / f"vigil-{STAMP}.coord",
        tmp_path / "remote" / STAMP / "coord",
    ):
        got = sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())
        assert got == ["brief.md", "notes.md", "sub/real.txt"]
        assert not list(base.rglob("__pycache__"))


def test_corrupt_db_copy_fails_and_ships_nothing(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backup, "_output_problems", lambda conn: ["integrity_check: broken"])
    remote = LocalRemote(tmp_path / "remote")
    res = _run(data, tmp_path, remote)
    assert not res.ok
    assert _names(remote) == []
    assert not list((tmp_path / "local").glob("vigil-*"))
    [ev] = _events(data)
    assert ev["ok"] is False and "integrity" in str(ev["error"]) and ev["integrity"] != "ok"


def test_vault_repo_failing_fsck_fails_and_ships_nothing(data: Path, tmp_path: Path) -> None:
    refs = data / "vault" / "o" / "r.git" / "refs" / "heads"
    (refs / "main").write_text("1" * 40 + "\n")  # a ref to an object that doesn't exist
    remote = LocalRemote(tmp_path / "remote")
    res = _run(data, tmp_path, remote)
    assert not res.ok
    assert _names(remote) == []
    assert not list((tmp_path / "local").glob("vigil-*"))
    [ev] = _events(data)
    assert ev["ok"] is False and ev["fsck"] == {"repos": 1, "failed": ["o/r.git"]}


def test_remote_difference_fails_the_run(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = backup._rsync_diff

    def tamper(src: Path, dst: str, *, is_dir: bool, ssh_e: str = "") -> list[str]:
        if not is_dir and src.name == "vigil.db":
            Path(dst).write_bytes(b"tampered")
        return real(src, dst, is_dir=is_dir, ssh_e=ssh_e)

    monkeypatch.setattr(backup, "_rsync_diff", tamper)
    res = _run(data, tmp_path, LocalRemote(tmp_path / "remote"))
    assert not res.ok
    [ev] = _events(data)
    assert ev["ok"] is False and ev["remote_verified"] is False
    # nothing is deleted: the failed copy stays, whole, under its .partial name, and the
    # real set name is never taken by an unverified copy
    kept = tmp_path / "remote" / f"{STAMP}.partial"
    assert kept.is_dir() and not (tmp_path / "remote" / STAMP).exists()
    assert (kept / "vigil.db").read_bytes() == b"tampered"
    assert (kept / "vault" / "o" / "r.git" / "HEAD").is_file()
    assert (kept / "coord" / "notes.md").is_file() and backup._ours(kept / backup.REMOTE_MARKER)
    assert (tmp_path / "local" / f"vigil-{STAMP}.db").is_file()  # the local set is kept too


def test_clean_run_leaves_only_the_final_set(data: Path, tmp_path: Path) -> None:
    res = _run(data, tmp_path, LocalRemote(tmp_path / "remote"))
    assert res.ok
    assert sorted(p.name for p in (tmp_path / "remote").iterdir()) == [STAMP]


def _ok_event(data: Path, stamp: str) -> None:
    s = Store.open(data / "vigil.db")
    s.add_event("backup", {"ok": True, "stamp": stamp, "remote": "r"}, "human")
    s.conn.close()


def _stamp(days: float) -> str:
    return (NOW - timedelta(days=days)).strftime("%Y%m%dT%H%M%SZ")


def test_retention_keeps_the_last_good_set_however_old(tmp_path: Path) -> None:
    remote = LocalRemote(tmp_path / "remote")
    old = _fake_set(remote, NOW - timedelta(days=20), marked=True)
    assert backup._remote_retention(remote, NOW, 14, {old}) == []
    assert old in _names(remote)


def test_retention_deletes_an_old_good_set_once_a_newer_good_one_exists(tmp_path: Path) -> None:
    remote = LocalRemote(tmp_path / "remote")
    old = _fake_set(remote, NOW - timedelta(days=20), marked=True)
    newer = _fake_set(remote, NOW - timedelta(days=16), marked=True)
    # newer is itself past 14 days but has no newer good set: it stays
    assert backup._remote_retention(remote, NOW, 14, {old, newer}) == [old]
    assert _names(remote) == [newer]


def test_a_bad_set_never_counts_as_a_newer_good_one(tmp_path: Path) -> None:
    remote = LocalRemote(tmp_path / "remote")
    old = _fake_set(remote, NOW - timedelta(days=20), marked=True)
    newer = _stamp(2)
    for suffix in (".bad", ".partial"):
        d = remote.root_path / f"{newer}{suffix}"
        d.mkdir()
        (d / backup.REMOTE_MARKER).write_text("0123456789abcdef")
    # an ok event exists for `newer`, but only a .bad/.partial copy is on the remote
    assert backup._remote_retention(remote, NOW, 14, {old, newer}) == []
    assert old in _names(remote)
    # an unmarked plain copy does not count either
    (remote.root_path / newer).mkdir()
    assert backup._remote_retention(remote, NOW, 14, {old, newer}) == []


def test_old_bad_sets_follow_the_14_day_rule(tmp_path: Path) -> None:
    remote = LocalRemote(tmp_path / "remote")
    good_old = _fake_set(remote, NOW - timedelta(days=30), marked=True)
    good_new = _fake_set(remote, NOW - timedelta(days=1), marked=True)
    bad = f"{_stamp(20)}.bad"
    (remote.root_path / bad).mkdir()
    (remote.root_path / bad / backup.REMOTE_MARKER).write_text("0123456789abcdef")
    assert sorted(backup._remote_retention(remote, NOW, 14, {good_old, good_new})) == sorted(
        [good_old, bad]
    )
    assert _names(remote) == [good_new]


def test_verify_ignores_directory_mtime_but_sees_content(tmp_path: Path) -> None:
    import os

    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    (src / "vigil.db").write_text("same")
    (dst / "vigil.db").write_text("same")
    os.utime(src / "vigil.db", (1_700_000_000, 1_700_000_000))
    os.utime(dst / "vigil.db", (1_700_000_000, 1_700_000_000))
    os.utime(dst, (1_600_000_000, 1_600_000_000))  # the parent's mtime differs
    assert backup._rsync_diff(src / "vigil.db", f"{dst}/vigil.db", is_dir=False) == []
    assert backup._rsync_diff(src, f"{dst}", is_dir=True) == []
    (dst / "vigil.db").write_text("diff")
    os.utime(dst / "vigil.db", (1_700_000_000, 1_700_000_000))
    assert backup._rsync_diff(src / "vigil.db", f"{dst}/vigil.db", is_dir=False) != []


def _fake_set(remote: backup.RsyncRemote, when: datetime, *, marked: bool) -> str:
    name = when.strftime("%Y%m%dT%H%M%SZ")
    d = remote.root_path / name
    d.mkdir()
    (d / "vigil.db").write_text("x")
    if marked:
        (d / backup.REMOTE_MARKER).write_text("0123456789abcdef")
    return name


def test_remote_retention_keeps_unmarked_and_recent(data: Path, tmp_path: Path) -> None:
    remote = LocalRemote(tmp_path / "remote")
    old = _fake_set(remote, NOW - timedelta(days=15), marked=True)
    theirs = _fake_set(remote, NOW - timedelta(days=15, hours=1), marked=False)
    recent = _fake_set(remote, NOW - timedelta(days=13), marked=True)
    (remote.root_path / "notes").mkdir()  # name doesn't match the stamp pattern
    (remote.root_path / "notes" / backup.REMOTE_MARKER).write_text("0123456789abcdef")
    res = _run(data, tmp_path, remote)
    assert res.ok
    names = _names(remote)
    assert old not in names
    assert theirs in names and recent in names and "notes" in names and STAMP in names
    [ev] = _events(data)
    assert ev["retention_removed"] == [old]


def test_remote_retention_leaves_contents_of_kept_dirs_alone(data: Path, tmp_path: Path) -> None:
    remote = LocalRemote(tmp_path / "remote")
    old = _fake_set(remote, NOW - timedelta(days=15), marked=True)
    keep = _fake_set(remote, NOW - timedelta(days=13), marked=True)
    (remote.root_path / old / "sub").mkdir()
    (remote.root_path / old / "sub" / "f").write_text("x")
    assert remote.remove_if_ours(old)
    assert _names(remote) == [keep]
    assert (remote.root_path / keep / "vigil.db").read_text() == "x"
    with pytest.raises(backup.BackupError):
        remote.remove_if_ours("../x")
    with pytest.raises(backup.BackupError):
        remote.remove_if_ours("notes")


def test_remote_symlink_set_is_not_removed(data: Path, tmp_path: Path) -> None:
    remote = LocalRemote(tmp_path / "remote")
    target = tmp_path / "elsewhere"
    target.mkdir()
    (target / backup.REMOTE_MARKER).write_text("0123456789abcdef")
    (remote.root_path / "20260101T000000Z").symlink_to(target)
    assert not remote.remove_if_ours("20260101T000000Z")
    assert (target / backup.REMOTE_MARKER).exists()


def test_rsync_remote_uses_key_by_path_and_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake(args: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(backup.subprocess, "run", fake)
    r = backup.RsyncRemote.parse("tower:", "/Users/x/.ssh/vigil-backup")
    assert r.target("20261031T031500Z") == "tower:20261031T031500Z"
    r.names()
    e = calls[-1][calls[-1].index("-e") + 1]
    assert "-i /Users/x/.ssh/vigil-backup" in e and "IdentitiesOnly=yes" in e
    assert backup.RsyncRemote.parse("tower:sub/dir").root == "tower:sub/dir/"
    for bad in ("-oProxyCommand=x:", "tower:a b", "tower", "tower:../x", "tower:~/x", "tower:$(x)"):
        with pytest.raises(backup.BackupError):
            backup.RsyncRemote.parse(bad)
    with pytest.raises(backup.BackupError):
        backup.RsyncRemote.parse("tower:", "k; rm")


# --- health ---------------------------------------------------------------------


def _record(store: Store, ok: bool, age_h: float) -> None:
    eid = store.add_event("backup", {"ok": ok, "stamp": "s", "remote": "h:p"}, "human")
    store.x(
        "UPDATE events SET ts=? WHERE id=?", (iso(datetime.now(UTC) - timedelta(hours=age_h)), eid)
    )


def _degraded(client: TestClient, tokens: Tokens) -> list[str]:
    body = client.get("/api/health", headers=auth(tokens.read)).json()
    return list(body["degraded"])


def test_health_backup_fresh_ok(client: TestClient, services: Services, tokens: Tokens) -> None:
    _record(services.store, True, 35)
    assert "backup" not in _degraded(client, tokens)


def test_health_backup_stale_at_37h(client: TestClient, services: Services, tokens: Tokens) -> None:
    _record(services.store, True, 37)
    assert "backup" in _degraded(client, tokens)


def test_health_backup_none_is_degraded(
    client: TestClient, services: Services, tokens: Tokens
) -> None:
    assert "backup" in _degraded(client, tokens)


def test_health_backup_failed_newer_than_stale_good(
    client: TestClient, services: Services, tokens: Tokens
) -> None:
    _record(services.store, True, 40)
    _record(services.store, False, 2)
    assert "backup" in _degraded(client, tokens)


def test_health_reads_the_store_each_request(
    client: TestClient, services: Services, tokens: Tokens
) -> None:
    assert "backup" in _degraded(client, tokens)
    _record(services.store, True, 1)
    assert "backup" not in _degraded(client, tokens)


# --- GNU rsync only -----------------------------------------------------------------

OPENRSYNC = "#!/bin/sh\necho 'openrsync: protocol version 29'\n"
GNU = "#!/bin/sh\necho 'rsync  version 3.4.1  protocol version 32'\n"


def _fake(path: Path, text: str) -> str:
    path.write_text(text)
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def real_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switch the test-only version-check skip off: the production path."""
    monkeypatch.setattr(backup, "_TEST_SKIP_RSYNC_CHECK", False)


def test_openrsync_is_refused_before_any_copy(
    data: Path, tmp_path: Path, real_check: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _fake(tmp_path / "rsync", OPENRSYNC)
    remote = LocalRemote(tmp_path / "remote")
    res = _run(data, tmp_path, remote, rsync=fake)
    assert not res.ok
    assert res.event["ok"] is False
    assert res.event["error"] == (
        f"rsync is openrsync (or not GNU rsync >= 3.1) at {fake}; "
        "install GNU rsync (brew install rsync) or set VIGIL_RSYNC"
    )
    assert res.event["rsync"] == {"path": fake, "version": "openrsync: protocol version 29"}
    assert not (tmp_path / "local").exists()
    assert _names(remote) == []
    assert _events(data)[-1]["ok"] is False


def test_unparseable_and_old_gnu_are_refused(tmp_path: Path) -> None:
    for text in ("garbage", "rsync  version 3.0.9  protocol version 30", ""):
        fake = _fake(tmp_path / "r", f"#!/bin/sh\necho '{text}'\n")
        with pytest.raises(backup.RsyncRefused):
            backup.check_gnu_rsync(fake)


def test_gnu_version_passes(tmp_path: Path) -> None:
    assert (
        backup.check_gnu_rsync(_fake(tmp_path / "r", GNU))
        == "rsync  version 3.4.1  protocol version 32"
    )


def test_gnu_check_then_full_run(data: Path, tmp_path: Path, real_check: None) -> None:
    import shutil

    real = shutil.which("rsync")
    assert real
    # The fake reports GNU for --version and execs the real rsync otherwise.
    fake = _fake(
        tmp_path / "rsync",
        f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo "rsync  version 3.4.1  protocol'
        f' version 32"; exit 0; fi\nexec {real} "$@"\n',
    )
    res = _run(data, tmp_path, LocalRemote(tmp_path / "remote"), rsync=fake)
    assert res.ok, res.event
    assert res.event["rsync"]["path"] == fake  # type: ignore[index]


def test_health_lists_backup_rsync(
    client: TestClient, services: Services, tokens: Tokens, data: Path, tmp_path: Path
) -> None:
    services.store.add_event("backup", {"ok": False, "stamp": "s", "rsync_refused": True}, "human")
    d = _degraded(client, tokens)
    assert "backup" in d and "backup-rsync" in d
    services.store.add_event("backup", {"ok": False, "stamp": "t"}, "human")
    assert "backup-rsync" not in _degraded(client, tokens)


def test_resolution_order(monkeypatch: pytest.MonkeyPatch) -> None:
    brew = "/opt/homebrew/bin/rsync"
    monkeypatch.setattr(backup, "_is_executable", lambda p: p == brew)
    monkeypatch.delenv("VIGIL_RSYNC", raising=False)
    assert backup.resolve_rsync("/x/cli") == "/x/cli"
    monkeypatch.setenv("VIGIL_RSYNC", "/x/env")
    assert backup.resolve_rsync("/x/cli") == "/x/cli"
    assert backup.resolve_rsync(None) == "/x/env"
    monkeypatch.delenv("VIGIL_RSYNC")
    assert backup.resolve_rsync(None) == brew
    monkeypatch.setattr(backup, "_is_executable", lambda p: False)
    assert backup.resolve_rsync(None) == "rsync"


def test_every_subprocess_call_uses_the_resolved_binary(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_run = subprocess.run
    argv0: list[str] = []

    def spy(args: list[str], *a: object, **k: object) -> subprocess.CompletedProcess[str]:
        if args[0] != "git" and "git" not in str(args[0]).rsplit("/", 1)[-1]:
            argv0.append(args[0])
        return real_run(args, *a, **k)  # type: ignore[call-overload,no-any-return]

    import shutil

    real = shutil.which("rsync")
    assert real
    monkeypatch.setattr(backup.subprocess, "run", spy)
    res = _run(data, tmp_path, LocalRemote(tmp_path / "remote"), rsync=real)
    assert res.ok, res.event
    assert argv0 and set(argv0) == {real}


def test_no_bare_rsync_literal_in_backup_py() -> None:
    src = Path(backup.__file__).read_text()
    assert '["rsync",' not in src and '\n            "rsync",' not in src

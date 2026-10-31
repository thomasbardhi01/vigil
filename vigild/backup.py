"""`vigil backup` and `vigil restore` (verify only; issue #23): the durability
story until there is a second machine.

A backup *set* is in the destination, named by UTC time:
`vigil-YYYYMMDDTHHMMSSZ.db` (SQLite online backup of `<data>/vigil.db`, mode
600), `vigil-YYYYMMDDTHHMMSSZ.vault/` (rsync of `<data>/vault/`) and
`vigil-YYYYMMDDTHHMMSSZ.marker` (holds the run id; a plain copy of the temp
marker, made with an exclusive create, so it works on exFAT and FAT drives
that have no hard links and is never written through a planted symlink).
`freshness` says whether the newest complete set is recent (`vigil doctor`).
Retention prunes only sets
whose marker holds a run id this tool wrote, so a person's own file with a matching name is never
removed. A set is built in `.vigil-<stamp>.tmp/` (marker inside) and moved out.
This module never opens anything under `~/.config/vigil/`; the destination
comes from the host (`--dest` or `VIGIL_BACKUP_DIR`), never from the repo.
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from vigild.db import MIGRATIONS, Store
from vigild.gitsafe import GitError, git
from vigild.provenance import Provenance

REPO_ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = Path.home() / ".config" / "vigil"
_STAMP = r"\d{8}T\d{6}Z"
_MARKER = re.compile(rf"^vigil-({_STAMP})\.marker$")
_RUN_ID = re.compile(r"^[0-9a-f]{16}$")
_TMP = re.compile(rf"^\.vigil-{_STAMP}\.tmp$")
TMP_MARKER = ".vigil-backup"
RSYNC_VANISHED = 24
RSYNC_FLAGS = ["-a", "--safe-links", "--no-specials", "--no-devices"]
COORD_EXCLUDES = ["--exclude=*.pid", "--exclude=__pycache__", "--exclude=*.tmp"]
REMOTE_MARKER = "vigil.marker"
_STAMP_NAME = re.compile(rf"^{_STAMP}$")


class BackupError(Exception):
    pass


@dataclass(frozen=True)
class BackupSet:
    db: Path
    vault: Path
    warnings: list[str] = field(default_factory=list)
    coord: Path | None = None
    marker: Path | None = None
    stamp: str = ""
    pruned: list[Path] = field(default_factory=list)


@contextlib.contextmanager
def _umask(mask: int) -> Iterator[None]:
    old = os.umask(mask)
    try:
        yield
    finally:
        os.umask(old)


def _inside(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def _check_dest(data: Path, dest: Path) -> Path:
    dest = dest.expanduser().resolve()
    for name, bad in (
        ("the data dir", data.resolve()),
        ("the repo", REPO_ROOT),
        ("~/.config/vigil", SECRETS_DIR.resolve()),
    ):
        if _inside(dest, bad):
            raise BackupError(f"destination {dest} is inside {name}")
        if _inside(bad, dest):
            raise BackupError(f"destination {dest} contains {name}")
    return dest


def run_backup(
    data: Path,
    dest: Path,
    *,
    now: datetime | None = None,
    keep_days: int | None = 14,
    checks: dict[str, object] | None = None,
) -> BackupSet:
    """Back up `<data>/vigil.db`, `<data>/vault/` and `<data>/coord/` into `dest`,
    check the copies (integrity_check; `git fsck` on every bare repo in the copied
    vault), then prune. A failed check discards the set and raises. `checks`, if
    given, is filled with the results (also on failure)."""
    checks = checks if checks is not None else {}
    src = data / "vigil.db"
    if not src.is_file():
        raise BackupError(f"no database at {src}")
    dest = _check_dest(data, dest)
    now = (now or datetime.now(UTC)).astimezone(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    run_id = secrets.token_hex(8)
    warnings: list[str] = []
    with _umask(0o077):
        dest.mkdir(parents=True, exist_ok=True)
        os.chmod(dest, 0o700)
        _clean_tmp(dest)
        final_db = dest / f"vigil-{stamp}.db"
        final_vault = dest / f"vigil-{stamp}.vault"
        final_marker = dest / f"vigil-{stamp}.marker"
        final_coord = dest / f"vigil-{stamp}.coord"
        if any(os.path.lexists(p) for p in (final_db, final_vault, final_marker, final_coord)):
            raise BackupError(f"backup set {stamp} already exists")
        work = dest / f".vigil-{stamp}.tmp"
        work.mkdir()
        (work / TMP_MARKER).write_text(run_id)
        placed: list[Path] = []  # what this run put in dest; only these are discarded
        try:
            _copy_db(src, work / "db", checks)
            warnings += _copy_tree(data / "vault", work / "vault")
            warnings += _copy_tree(data / "coord", work / "coord", COORD_EXCLUDES)
            _fsck_vault(work / "vault", checks)
            # The marker lands first, so a piece in dest is never unmarked; a
            # set cut short by a kill is marked and prune removes it when old.
            # A copy, not a hard link (exFAT/FAT have none); "x" never opens an
            # existing file or a symlink at that name.
            with open(final_marker, "x") as f:
                placed.append(final_marker)
                f.write(run_id)
            os.rename(work / "db", final_db)
            placed.append(final_db)
            os.rename(work / "vault", final_vault)
            placed.append(final_vault)
            os.rename(work / "coord", final_coord)
            placed.append(final_coord)
        except BaseException:
            _discard(placed)
            raise
        finally:
            shutil.rmtree(work, ignore_errors=True)
    pruned = prune(dest, keep_days, now=now) if keep_days is not None else []
    return BackupSet(final_db, final_vault, warnings, final_coord, final_marker, stamp, pruned)


def _discard(paths: list[Path]) -> None:
    for p in paths:
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)


def _output_problems(conn: sqlite3.Connection) -> list[str]:
    problems: list[str] = []
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    if [r[0] for r in rows] != ["ok"]:
        problems.append("integrity_check: " + "; ".join(str(r[0]) for r in rows[:5]))
    if int(conn.execute("PRAGMA user_version").fetchone()[0]) <= 0:
        problems.append("user_version is 0")
    return problems


def _copy_db(src: Path, out: Path, checks: dict[str, object] | None = None) -> None:
    # A normal connection and the online backup API: a consistent snapshot
    # under WAL while vigild runs. It may create -wal/-shm beside the source;
    # that is accepted. The umask makes sqlite create the output 600. The
    # output is checked before the caller renames it into place.
    s = sqlite3.connect(str(src), timeout=30)
    d = sqlite3.connect(str(out))
    try:
        try:
            s.backup(d)
            d.execute("PRAGMA journal_mode=DELETE")
            d.commit()
            problems = _output_problems(d)
        except sqlite3.Error as e:
            if checks is not None:
                checks["integrity"] = f"error: {e}"
            raise BackupError(f"database backup failed: {e}") from e
    finally:
        d.close()
        s.close()
    if checks is not None:
        checks["integrity"] = "; ".join(problems) if problems else "ok"
    if problems:
        out.unlink(missing_ok=True)
        raise BackupError("backup output failed its check: " + "; ".join(problems))
    os.chmod(out, 0o600)


def _copy_tree(src: Path, out: Path, excludes: list[str] | None = None) -> list[str]:
    out.mkdir()
    if not src.is_dir():
        return []
    r = subprocess.run(
        ["rsync", *RSYNC_FLAGS, *(excludes or []), "--", f"{src}/", f"{out}/"],
        capture_output=True,
        text=True,
    )
    if r.returncode == RSYNC_VANISHED:
        return [f"rsync: some files vanished while copying {src.name}"]
    if r.returncode != 0:
        raise BackupError(f"rsync failed ({r.returncode}): {r.stderr.strip()[:300]}")
    return []


def _fsck_vault(vault: Path, checks: dict[str, object]) -> None:
    """`git fsck --no-dangling` (through gitsafe) on every bare repo in the copied vault."""
    repos = sorted(
        p.parent
        for p in vault.rglob("HEAD")
        if p.is_file() and not p.is_symlink() and (p.parent / "objects").is_dir()
    )
    failed: list[str] = []
    for repo in repos:
        try:
            git(repo, "fsck", "--no-dangling", timeout=3600)
        except GitError, subprocess.TimeoutExpired:
            failed.append(str(repo.relative_to(vault)))
    checks["fsck"] = {"repos": len(repos), "failed": failed}
    if failed:
        raise BackupError("git fsck failed on: " + ", ".join(failed))


def _ours(marker: Path) -> bool:
    """True if `marker` is a plain file holding exactly a run id this tool wrote."""
    try:
        if marker.is_symlink() or not marker.is_file() or marker.stat().st_size > 64:
            return False
        return bool(_RUN_ID.fullmatch(marker.read_text()))
    except OSError, UnicodeDecodeError:
        return False


def _clean_tmp(dest: Path) -> None:
    """Remove leftovers of failed runs: `.vigil-<stamp>.tmp/` dirs that hold
    this tool's marker. Anything else is not ours."""
    for p in dest.iterdir():
        if _TMP.match(p.name) and p.is_dir() and not p.is_symlink() and _ours(p / TMP_MARKER):
            shutil.rmtree(p, ignore_errors=True)


def prune(dest: Path, keep_days: int, *, now: datetime) -> list[Path]:
    """Remove dated sets older than `keep_days`, only those with the marker."""
    cutoff = now - timedelta(days=keep_days)
    removed: list[Path] = []
    for m in sorted(dest.iterdir()):
        mm = _MARKER.match(m.name)
        if not mm or not _ours(m):
            continue
        when = datetime.strptime(mm.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if when >= cutoff:
            continue
        db = dest / f"vigil-{mm.group(1)}.db"
        for tree in (dest / f"vigil-{mm.group(1)}.vault", dest / f"vigil-{mm.group(1)}.coord"):
            if tree.is_dir() and not tree.is_symlink():
                shutil.rmtree(tree)
                removed.append(tree)
        if db.is_file() and not db.is_symlink():
            db.unlink()
            removed.append(db)
        m.unlink()
        removed.append(m)
    return removed


def verify_backup(db: Path) -> list[str]:
    """Open `db` read-only and check it. Returns problems (empty: fine). Writes
    nothing: `mode=ro` plus `immutable=1` keeps sqlite from making -wal/-shm."""
    if not db.is_file():
        return [f"{db} does not exist"]
    try:
        conn = sqlite3.connect(f"file:{quote(str(db))}?mode=ro&immutable=1", uri=True)
    except sqlite3.Error as e:
        return [f"cannot open read-only: {e}"]
    try:
        try:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        except sqlite3.Error as e:
            return [f"not a readable database: {e}"]
    finally:
        conn.close()
    problems: list[str] = []
    if [r[0] for r in rows] != ["ok"]:
        problems.append("integrity_check: " + "; ".join(str(r[0]) for r in rows[:5]))
    if version != len(MIGRATIONS):
        problems.append(f"user_version is {version}, expected {len(MIGRATIONS)}")
    return problems


MAX_AGE = timedelta(hours=36)


def freshness(dest: Path, *, now: datetime, max_age: timedelta = MAX_AGE) -> tuple[bool, str]:
    """Is the newest complete set in `dest` at most `max_age` old? A complete
    set is a marker that is ours, a regular-file db and a vault directory. Age
    is `now` minus the stamp in the name. The note never holds the path."""
    try:
        names = sorted(p.name for p in dest.iterdir())
    except OSError as e:
        return False, f"destination unreachable: {type(e).__name__}"
    newest: datetime | None = None
    for name in names:
        mm = _MARKER.match(name)
        if not mm or not _ours(dest / name):
            continue
        db, vault = dest / f"vigil-{mm.group(1)}.db", dest / f"vigil-{mm.group(1)}.vault"
        if not (db.is_file() and not db.is_symlink() and vault.is_dir() and not vault.is_symlink()):
            continue
        when = datetime.strptime(mm.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if newest is None or when > newest:
            newest = when
    if newest is None:
        return False, "no complete backup set"
    age = now.astimezone(UTC) - newest
    note = (
        f"newest set {newest.strftime('%Y%m%dT%H%M%SZ')}, {int(age.total_seconds() // 3600)}h old"
    )
    return age <= max_age, note


# --- the nightly off-machine run --------------------------------------------------------

_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]*$")
_RPATH = re.compile(r"^[A-Za-z0-9_./-]+$")
_KEYPATH = re.compile(r"^[A-Za-z0-9_./~-]+$")


class RsyncRemote:
    """The tower side accepts only rsync (a key restricted to `rrsync ~/vigil-backups`), so
    every remote operation here is an rsync: ship, verify, list, fetch a marker, delete.
    `root` is what a set name is appended to: `host:` (rrsync's root is fixed on the
    tower), `host:sub/dir/`, or a local directory for tests. A host value (`--remote` or
    `VIGIL_BACKUP_REMOTE`), never in the repo. The key is passed by path only; this
    module never opens it. Names that reach rsync are stamp-validated."""

    def __init__(self, root: str, ssh_key: str | None = None) -> None:
        self.root = root if root.endswith(("/", ":")) else root + "/"
        self.label = self.root
        opts = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]
        if ssh_key:
            if not _KEYPATH.match(ssh_key):
                raise BackupError("ssh key path has characters that are not allowed")
            opts = ["-i", ssh_key, "-o", "IdentitiesOnly=yes", *opts]
        self.ssh_e = "ssh " + " ".join(opts)

    @classmethod
    def parse(cls, value: str, ssh_key: str | None = None) -> RsyncRemote:
        host, sep, sub = value.partition(":")
        if not sep or not _HOST.match(host) or (sub and not _RPATH.match(sub)):
            raise BackupError("remote must look like host: or host:sub/dir (no ~, no spaces)")
        if ".." in sub.split("/") or sub.startswith(("/", "~")):
            raise BackupError("remote path is relative to the rrsync root, without '..'")
        return cls(f"{host}:{sub}", ssh_key)

    def target(self, name: str) -> str:
        return f"{self.root}{name}"

    @staticmethod
    def _check_name(name: str) -> None:
        if not _STAMP_NAME.match(name):
            raise BackupError(f"not a backup set name: {name!r}")

    def _rsync(self, *args: str, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["rsync", "-e", self.ssh_e, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def mkdir(self, name: str) -> None:
        """Create the set directory by rsyncing an empty directory onto it."""
        self._check_name(name)
        with tempfile.TemporaryDirectory(prefix=".vigil-empty-") as empty:
            r = self._rsync("-a", "--", f"{empty}/", f"{self.target(name)}/")
        if r.returncode != 0:
            raise BackupError(f"remote create failed ({r.returncode}): {r.stderr.strip()[:200]}")

    def names(self) -> list[str]:
        """Real directories at the remote root (`rsync --list-only`)."""
        r = self._rsync("--list-only", "--", self.root, timeout=300)
        if r.returncode != 0:
            raise BackupError(f"remote listing failed ({r.returncode}): {r.stderr.strip()[:200]}")
        out: list[str] = []
        for line in r.stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) == 5 and parts[0].startswith("d") and parts[4] != ".":
                out.append(parts[4])
        return sorted(out)

    def _marker_is_ours(self, name: str) -> bool:
        with tempfile.TemporaryDirectory(prefix=".vigil-marker-") as tmp:
            r = self._rsync(
                "-a", "--", self.target(f"{name}/{REMOTE_MARKER}"), f"{tmp}/m", timeout=300
            )
            return r.returncode == 0 and _ours(Path(tmp) / "m")

    def remove_if_ours(self, name: str) -> bool:
        """Delete set `name` only if it is a stamp-named directory whose marker is a plain
        file holding a run id (the same guard as the local prune). The delete is an rsync
        of an empty directory with `--delete` and filter rules that include only
        `/<name>` and what is under it; `--exclude=*` protects every other path."""
        self._check_name(name)
        if name not in self.names() or not self._marker_is_ours(name):
            return False
        with tempfile.TemporaryDirectory(prefix=".vigil-empty-") as empty:
            r = self._rsync(
                "-r", "--delete",
                f"--include=/{name}", f"--include=/{name}/***", "--exclude=*",
                "--", f"{empty}/", self.root,
            )  # fmt: skip
        if r.returncode != 0:
            raise BackupError(f"remote delete failed ({r.returncode}): {r.stderr.strip()[:200]}")
        return True


def _rsync_diff(src: Path, dst: str, *, is_dir: bool, ssh_e: str = "ssh") -> list[str]:
    """Differences `rsync -a --dry-run --checksum --itemize-changes` reports (none: same)."""
    # A single file is compared through its parent directories with an include filter:
    # a lone-file dry run reports a difference even for identical files.
    filt: list[str] = []
    if is_dir:
        a, b = f"{src}/", f"{dst}/"
    else:
        a, b = f"{src.parent}/", dst.rsplit("/", 1)[0] + "/"
        filt = [f"--include=/{src.name}", "--exclude=*"]
    r = subprocess.run(
        [
            "rsync", *RSYNC_FLAGS, "--dry-run", "--checksum", "--itemize-changes",
            *filt, "-e", ssh_e, "--", a, b,
        ],
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )  # fmt: skip
    if r.returncode not in (0, RSYNC_VANISHED):
        raise BackupError(f"remote verify failed ({r.returncode}): {r.stderr.strip()[:200]}")
    # A directory whose only difference is its mtime (GNU rsync lists the root `./` when
    # its mtime moved, e.g. a sibling was written later) is not a content difference.
    return [
        line
        for line in r.stdout.splitlines()
        if line.strip() and not re.fullmatch(r"\.d[.t]+ .*", line)
    ]


def _ship_piece(src: Path, dst: str, *, is_dir: bool, ssh_e: str = "ssh") -> None:
    a, b = (f"{src}/", f"{dst}/") if is_dir else (str(src), dst)
    r = subprocess.run(
        ["rsync", *RSYNC_FLAGS, "-e", ssh_e, "--", a, b],
        capture_output=True,
        text=True,
        timeout=3600,
        check=False,
    )
    if r.returncode not in (0, RSYNC_VANISHED):
        raise BackupError(f"ship failed ({r.returncode}): {r.stderr.strip()[:200]}")


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())


@dataclass
class NightlyResult:
    ok: bool
    stamp: str
    event: dict[str, object]


def run_nightly(
    data: Path,
    dest: Path,
    remote: Any,
    *,
    now: datetime | None = None,
    keep_days: int = 14,
) -> NightlyResult:
    """Build the local set, verify it, ship it to `remote` (a `SshRemote`, or a test
    double with `label`, `target`, `mkdir`, `names`, `remove_if_ours`), verify the remote
    copy, apply remote retention, and record a `backup` event in the store. A failed run
    does not raise: the failure is the event (`ok: false`) and the result."""
    started = time.monotonic()
    now = (now or datetime.now(UTC)).astimezone(UTC)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    checks: dict[str, object] = {}
    ev: dict[str, object] = {
        "ok": False,
        "stamp": stamp,
        "remote": remote.label,
        "sizes": {},
        "integrity": "not run",
        "fsck": {"repos": 0, "failed": []},
        "remote_verified": False,
        "retention_removed": [],
        "local_pruned": 0,
    }
    try:
        made = run_backup(data, dest, now=now, keep_days=keep_days, checks=checks)
        ev["sizes"] = {
            "db": _size(made.db),
            "vault": _size(made.vault),
            "coord": _size(made.coord) if made.coord else 0,
        }
        ev["local_pruned"] = len(made.pruned)
        ev.update(checks)
        ev["remote_verified"] = _ship(made, remote)
        ev["retention_removed"] = _remote_retention(remote, now, keep_days)
        ev["ok"] = True
    except (BackupError, OSError, subprocess.TimeoutExpired) as e:
        ev.update(checks)
        ev["error"] = str(e)[:300]
    ev["duration_s"] = round(time.monotonic() - started, 2)
    store = Store.open(data / "vigil.db")
    try:
        store.add_event("backup", ev, Provenance.HUMAN)
    finally:
        store.conn.close()
    return NightlyResult(bool(ev["ok"]), stamp, ev)


def _ship(made: BackupSet, remote: Any) -> bool:
    assert made.coord is not None and made.marker is not None
    remote.mkdir(made.stamp)
    # Files go under the name they have on the remote (rsync's itemized dry-run compares
    # by name), so stage links or copies of the db and marker under those names.
    with tempfile.TemporaryDirectory(prefix=f".vigil-{made.stamp}.ship-", dir=made.db.parent) as t:
        stage = Path(t)
        for src, name in ((made.db, "vigil.db"), (made.marker, REMOTE_MARKER)):
            try:
                os.link(src, stage / name)
            except OSError:  # no hard links (exFAT/FAT)
                shutil.copy2(src, stage / name)
        pieces = [
            (stage / "vigil.db", f"{made.stamp}/vigil.db", False),
            (made.vault, f"{made.stamp}/vault", True),
            (made.coord, f"{made.stamp}/coord", True),
            # last: marks the set complete
            (stage / REMOTE_MARKER, f"{made.stamp}/{REMOTE_MARKER}", False),
        ]
        for src, name, is_dir in pieces:
            _ship_piece(src, remote.target(name), is_dir=is_dir, ssh_e=remote.ssh_e)
        diffs: list[str] = []
        for src, name, is_dir in pieces:
            diffs += _rsync_diff(src, remote.target(name), is_dir=is_dir, ssh_e=remote.ssh_e)
    if diffs:
        remote.remove_if_ours(made.stamp)
        raise BackupError("remote copy differs from the local set: " + "; ".join(diffs[:3]))
    return True


def _remote_retention(remote: Any, now: datetime, keep_days: int) -> list[str]:
    """Remove only directories named like a stamp, older than `keep_days`, that hold this
    tool's marker (the same guard as the local prune)."""
    cutoff = now - timedelta(days=keep_days)
    removed: list[str] = []
    for name in remote.names():
        if not _STAMP_NAME.match(name):
            continue
        when = datetime.strptime(name, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if when < cutoff and remote.remove_if_ours(name):
            removed.append(name)
    return removed


def backup_degraded(store: Store, *, now: datetime | None = None) -> bool:
    """True when the latest `ok: true` backup event is older than 36 h, or none exists.
    Read from the store at call time (the health endpoint calls it per request)."""
    now = now or datetime.now(UTC)
    rows = store.q(
        "SELECT ts FROM events WHERE type='backup' AND json_extract(data,'$.ok')=1"
        " ORDER BY ts DESC LIMIT 1"
    )
    if not rows:
        return True
    return now - datetime.fromisoformat(rows[0]["ts"]) > MAX_AGE

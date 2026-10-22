"""Per-task clones from a local mirror (B3), never `git worktree`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import git
from vigild.workspace import Workspace, WorkspaceError


@pytest.fixture
def ws(tmp_path: Path, fixture_repo: dict[str, Path]) -> Workspace:
    bare = fixture_repo["bare"]
    return Workspace(tmp_path / "data", remote_url=lambda repo: str(bare))


def test_mirror_then_clone(ws: Workspace) -> None:
    clone = ws.clone("o/fixture", "fx-0001-w1", branch="vigil/fx-0001-w1-doc", base="main")
    assert (clone / ".git").is_dir()  # self-contained, not a worktree's .git file
    assert git(clone, "rev-parse", "--abbrev-ref", "HEAD") == "vigil/fx-0001-w1-doc"
    assert (clone / "README.md").read_text() == "# fixture\n"
    assert (ws.data_dir / "mirrors" / "o" / "fixture.git").is_dir()


def test_clone_has_no_remote_and_copied_objects(ws: Workspace) -> None:
    clone = ws.clone("o/fixture", "fx-0001-w1", branch="vigil/fx-0001-w1-doc", base="main")
    assert git(clone, "remote") == ""  # the worker never pushes; vigild does, from the vault
    mirror = ws.data_dir / "mirrors" / "o" / "fixture.git"
    clone_objs = {p.stat().st_ino for p in (clone / ".git" / "objects").rglob("*") if p.is_file()}
    mirror_objs = {p.stat().st_ino for p in (mirror / "objects").rglob("*") if p.is_file()}
    assert not clone_objs & mirror_objs  # no hard links a worker could write through


def test_two_clones_are_independent(ws: Workspace) -> None:
    a = ws.clone("o/fixture", "fx-0001-w1", branch="vigil/a", base="main")
    b = ws.clone("o/fixture", "fx-0001-w2", branch="vigil/b", base="main")
    (a / "x.txt").write_text("a")
    assert not (b / "x.txt").exists()
    assert "vigil/a" not in git(b, "branch", "--list")


def test_mirror_refreshes(ws: Workspace, fixture_repo: dict[str, Path]) -> None:
    ws.clone("o/fixture", "fx-0001-w1", branch="vigil/a", base="main")
    seed = fixture_repo["seed"]
    (seed / "NEW.md").write_text("new\n")
    git(seed, "add", "NEW.md")
    git(seed, "commit", "-qm", "new")
    git(seed, "push", "-q", "origin", "main")
    c2 = ws.clone("o/fixture", "fx-0001-w2", branch="vigil/b", base="main")
    assert (c2 / "NEW.md").exists()


def test_task_json_is_written_and_ignored(ws: Workspace) -> None:
    clone = ws.clone("o/fixture", "fx-0001-w1", branch="vigil/a", base="main")
    ws.write_task(clone, {"task_id": "fx-0001-w1"})
    assert json.loads((clone / ".vigil" / "task.json").read_text())["task_id"] == "fx-0001-w1"
    assert git(clone, "status", "--porcelain") == ""


def test_mirror_ignores_ambient_git_config(
    ws: Workspace, tmp_path: Path, monkeypatch: object
) -> None:
    """Item 22: a global credential helper or insteadOf rule never applies."""
    marker = tmp_path / "HELPER-RAN"
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text(
        f'[credential]\n\thelper = !touch {marker}\n[url "{tmp_path}/nowhere/"]\n\tinsteadOf = /\n'
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))  # type: ignore[attr-defined]
    ws.clone("o/fixture", "fx-0001-w1", branch="vigil/a", base="main")
    assert not marker.exists()


def test_mirror_uses_a_read_token_when_configured(
    tmp_path: Path, fixture_repo: dict[str, Path]
) -> None:
    from contextlib import contextmanager

    asked: list[str] = []

    @contextmanager
    def token_for(repo: str):  # type: ignore[no-untyped-def]
        asked.append(repo)
        yield None

    w = Workspace(
        tmp_path / "d", remote_url=lambda r: str(fixture_repo["bare"]), token_for=token_for
    )
    w.clone("o/fixture", "fx-0001-w1", branch="vigil/a", base="main")
    assert asked == ["o/fixture"]


def test_mirror_updates_are_serialized_per_repo(ws: Workspace) -> None:
    import threading

    errors: list[Exception] = []

    def go(i: int) -> None:
        try:
            ws.clone("o/fixture", f"fx-0001-w{i}", branch=f"vigil/w{i}", base="main")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_read_only_overlays(ws: Workspace) -> None:
    clone = ws.clone("o/fixture", "fx-0001-w1", branch="vigil/a", base="main")
    mounts = {m.container: m for m in ws.overlays(clone)}
    for target in (
        "/work/.github",
        "/work/.claude",
        "/work/.opencode",
        "/work/.git/hooks",
        "/work/.git/config",
    ):
        assert mounts[target].read_only, target
    assert all(Path(m.host).exists() for m in mounts.values())


def test_task_ids_cannot_escape_the_clones_dir(ws: Workspace) -> None:
    with pytest.raises(WorkspaceError):
        ws.clone("o/fixture", "../evil", branch="vigil/a", base="main")
    with pytest.raises(WorkspaceError):
        ws.clone("o/fixture", "fx-1", branch="main", base="main")


def test_remove(ws: Workspace) -> None:
    clone = ws.clone("o/fixture", "fx-0001-w1", branch="vigil/a", base="main")
    ws.remove(clone)
    assert not clone.exists()

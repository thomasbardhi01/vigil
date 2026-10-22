"""The verifier (owner direction, review round 2): test results come only from
fresh checkouts vigild makes from the vault, run in containers it owns. Here a
local runner stands in for the container; tests/security/test_verifier_docker.py
runs the real one."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.conftest import git
from tests.harness import LocalTestRunner, finish_session
from vigild.verifier import Verifier, outcome
from vigild.workspace import Workspace

REPO = "o/fixture"
TID = "fx-0001-w1"
BRANCH = f"vigil/{TID}"


@pytest.fixture
def ws(tmp_path: Path, fixture_repo: dict[str, Path]) -> Workspace:
    seed = fixture_repo["seed"]
    (seed / "tests").mkdir()
    (seed / "tests" / "test_old.sh").write_text("exit 0\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "tests")
    git(seed, "push", "-q", "origin", "main")
    return Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"]))


def _session(ws: Workspace, tmp_path: Path, edit: object) -> tuple[Path, str, str]:
    clone = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    edit(clone)  # type: ignore[operator]
    out = tmp_path / "out"
    r = finish_session(clone, out, branch=BRANCH, base_sha=base)
    head = ws.import_result(REPO, TID, out, BRANCH, base, head=r["head"])
    return clone, base, head


def _verifier(ws: Workspace, runner: LocalTestRunner | None = None) -> Verifier:
    return Verifier(ws, runner or LocalTestRunner())


def _verify(v: Verifier, base: str, head: str, cmd: str, mff: bool = True) -> dict:
    return v.verify(
        repo=REPO,
        image="img",
        task_id=TID,
        base_sha=base,
        head=head,
        test_cmd=cmd,
        must_fail_first=mff,
    )


def test_after_runs_the_head_and_before_runs_the_base(ws: Workspace, tmp_path: Path) -> None:
    def edit(c: Path) -> None:
        (c / "docs" / "feature-map.md").write_text("| rate limit | 10 |\n")

    _, base, head = _session(ws, tmp_path, edit)
    rec = _verify(_verifier(ws), base, head, "grep -q 'rate limit' docs/feature-map.md")
    assert rec["after"]["sha"] == head and rec["after"]["outcome"] == "pass"
    assert rec["before"]["sha"] == base and rec["before"]["outcome"] == "fail"
    assert rec["before"]["applied"] == []
    assert rec["provenance"] == "human" and rec["source"] == "verifier"


def test_before_is_the_base_with_the_workers_new_and_changed_tests(
    ws: Workspace, tmp_path: Path
) -> None:
    """The new test exists at "before", the code it tests doesn't: it fails."""

    def edit(c: Path) -> None:
        (c / "tests" / "test_new.sh").write_text("test -f feature.txt\n")
        (c / "tests" / "test_old.sh").write_text("exit 0 # touched\n")
        (c / "feature.txt").write_text("x\n")

    _, base, head = _session(ws, tmp_path, edit)
    rec = _verify(_verifier(ws), base, head, "sh tests/test_new.sh")
    assert rec["before"]["applied"] == ["tests/test_new.sh", "tests/test_old.sh"]
    assert rec["before"]["outcome"] == "fail"
    assert rec["after"]["outcome"] == "pass"


def test_must_fail_first_off_runs_only_after(ws: Workspace, tmp_path: Path) -> None:
    _, base, head = _session(ws, tmp_path, lambda c: (c / "x.txt").write_text("x\n"))
    runner = LocalTestRunner()
    rec = _verify(_verifier(ws, runner), base, head, "true && test -f x.txt", mff=False)
    assert "before" not in rec and len(runner.calls) == 1


def test_each_run_gets_a_fresh_checkout_with_no_hooks(ws: Workspace, tmp_path: Path) -> None:
    _, base, head = _session(ws, tmp_path, lambda c: (c / "x.txt").write_text("x\n"))
    runner = LocalTestRunner()
    _verify(_verifier(ws, runner), base, head, "test -f x.txt")
    sources = [call["source"] for call in runner.calls]
    assert len(set(sources)) == 2
    for seen in runner.calls:
        assert seen["hooksPath"] == "/dev/null"
        assert not seen["worker_files"], seen
    assert not any(Path(s).exists() for s in sources), "checkouts are removed after the run"


def test_the_hook_forgery_and_a_fifo_record_change_nothing(ws: Workspace, tmp_path: Path) -> None:
    """The reviewer's forgery: commondir pointing at a copy with core.fsmonitor
    and hooks/post-commit that rewrite the old record path, plus a FIFO planted
    at that path. The verdict comes from the vault checkout; neither runs or
    is read, and the test still fails because the work doesn't pass it."""
    marker = tmp_path / "PWNED"
    out = tmp_path / "out"

    def edit(c: Path) -> None:
        evil = tmp_path / "evil-common"
        (evil / "hooks").mkdir(parents=True)
        script = f'#!/bin/sh\necho ran >> {marker}\necho \'{{"after":{{"outcome":"pass"}}}}\' > {out}/harness_tests.json\n'
        for name in ("post-commit", "pre-commit", "post-checkout"):
            (evil / "hooks" / name).write_text(script)
            (evil / "hooks" / name).chmod(0o755)
        fsm = tmp_path / "fsm.sh"
        fsm.write_text(script)
        fsm.chmod(0o755)
        (evil / "config").write_text(
            f"[core]\n\thooksPath = {evil / 'hooks'}\n\tfsmonitor = {fsm}\n"
        )
        for d in ("objects", "refs"):
            os.symlink(c / ".git" / d, evil / d)
        (c / ".git" / "commondir").write_text(str(evil) + "\n")
        (c / "docs" / "feature-map.md").write_text("nothing useful\n")
        out.mkdir(parents=True, exist_ok=True)
        os.mkfifo(out / "harness_tests.json")

    clone = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    edit(clone)
    # the stand-in commits with host git *without* the plants' reach (a real
    # harness pins its git); it doesn't matter here: what's tested is vigild's side
    git(clone, "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "add", "-A")
    subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "commit",
            "-qm",
            "w",
        ],
        cwd=clone,
        check=True,
        env={**os.environ, "GIT_COMMON_DIR": str(clone / ".git")},
    )
    git(
        clone,
        "bundle",
        "create",
        "-q",
        str(out / "result.bundle"),
        f"refs/heads/{BRANCH}",
        f"^{base}",
    )
    tip = git(clone, "rev-parse", BRANCH)
    head = ws.import_result(REPO, TID, out, BRANCH, base, head=tip)
    rec = _verify(_verifier(ws), base, head, "grep -q 'rate limit' docs/feature-map.md")
    assert rec["after"]["outcome"] == "fail"
    assert not marker.exists()
    assert (out / "harness_tests.json").is_fifo()  # never opened, never replaced


@pytest.mark.parametrize(
    ("code", "timed_out", "want"),
    [(0, False, "pass"), (1, False, "fail"), (127, False, "unknown"), (None, True, "timeout")],
)
def test_outcomes(code: int | None, timed_out: bool, want: str) -> None:
    assert outcome(code, timed_out) == want

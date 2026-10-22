"""The verifier (owner direction, review rounds 2 and 3): test results come only
from fresh checkouts vigild makes from the vault, with the base's runner files,
run in containers it owns. Here a local runner (bash with pipefail and errexit,
pytest asked for a JUnit report) stands in for the container;
tests/security/test_verifier_docker.py runs the real one."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import git
from tests.harness import LocalTestRunner, finish_session
from vigild.verifier import Verifier, judge, outcome, with_reports
from vigild.workspace import Workspace

REPO = "o/fixture"
TID = "fx-0001-w1"
BRANCH = f"vigil/{TID}"
CMD = "pytest -q tests"
FEATURE_TEST = "def test_flag():\n    from src.feature import flag\n\n    assert flag() is True\n"


@pytest.fixture
def ws(tmp_path: Path, fixture_repo: dict[str, Path]) -> Workspace:
    """A small Python repo: one passing test, one feature the worker turns on."""
    seed = fixture_repo["seed"]
    files = {
        "conftest.py": "import os, sys\nsys.path.insert(0, os.path.dirname(__file__))\n",
        "src/__init__.py": "",
        "src/feature.py": "def flag():\n    return False\n",
        "tests/test_old.py": "def test_old():\n    assert 1 + 1 == 2\n\n\ndef test_old_2():\n    assert True\n",
        "run_tests.sh": "pytest -q tests\n",
        "package.json": '{"scripts": {"test": "pytest -q tests"}}\n',
    }
    for name, text in files.items():
        (seed / name).parent.mkdir(parents=True, exist_ok=True)
        (seed / name).write_text(text)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "a python fixture")
    git(seed, "push", "-q", "origin", "main")
    return Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"]))


def _session(ws: Workspace, tmp_path: Path, edit: Callable[[Path], Any]) -> tuple[str, str]:
    clone = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    edit(clone)
    out = tmp_path / "out"
    r = finish_session(clone, out, branch=BRANCH, base_sha=base)
    return base, ws.import_result(REPO, TID, out, BRANCH, base, head=r["head"])


def _verify(
    ws: Workspace,
    base: str,
    head: str,
    cmd: str = CMD,
    *,
    mff: bool = True,
    config: list[str] | None = None,
    runner: LocalTestRunner | None = None,
) -> dict[str, Any]:
    return Verifier(ws, runner or LocalTestRunner()).verify(
        repo=REPO,
        image="img",
        task_id=TID,
        base_sha=base,
        head=head,
        test_cmd=cmd,
        must_fail_first=mff,
        runner_config=["conftest.py", "package.json"] if config is None else config,
    )


def _turn_on(c: Path) -> None:
    (c / "tests" / "test_flag.py").write_text(FEATURE_TEST)
    (c / "src" / "feature.py").write_text("def flag():\n    return True\n")


# --- the three runs --------------------------------------------------------------------------


def test_a_real_red_green_passes_every_check(ws: Workspace, tmp_path: Path) -> None:
    base, head = _session(ws, tmp_path, _turn_on)
    rec = _verify(ws, base, head)
    assert rec["base"]["sha"] == base and rec["base"]["tests"] == 2
    assert rec["before"]["sha"] == base and rec["before"]["outcome"] == "fail"
    assert rec["before"]["applied"] == ["tests/test_flag.py"]
    assert rec["after"]["sha"] == head and rec["after"]["outcome"] == "pass"
    assert rec["ids"] == {
        "checked": True,
        "failing_before": ["tests.test_flag::test_flag"],
        "not_passing_after": [],
    }
    assert rec["ran"]["ok"] and rec["ran"]["ids"] == {"base": 2, "head": 3}
    assert rec["provenance"] == "human" and rec["source"] == "verifier"


def test_must_fail_first_off_runs_base_and_after(ws: Workspace, tmp_path: Path) -> None:
    base, head = _session(ws, tmp_path, _turn_on)
    runner = LocalTestRunner()
    rec = _verify(ws, base, head, mff=False, runner=runner)
    assert "before" not in rec and len(runner.calls) == 2


def test_each_run_gets_a_fresh_checkout_with_no_hooks(ws: Workspace, tmp_path: Path) -> None:
    base, head = _session(ws, tmp_path, _turn_on)
    runner = LocalTestRunner()
    _verify(ws, base, head, runner=runner)
    sources = [call["source"] for call in runner.calls]
    assert len(set(sources)) == 3
    for seen in runner.calls:
        assert seen["hooksPath"] == "/dev/null"
        assert not seen["worker_files"], seen
    assert not any(Path(s).exists() for s in sources), "checkouts are removed after the run"


def test_the_hook_forgery_and_a_fifo_record_change_nothing(ws: Workspace, tmp_path: Path) -> None:
    """The reviewer's forgery (round 2): commondir pointing at a copy with
    core.fsmonitor and hooks/post-commit that rewrite the old record path, plus
    a FIFO planted at that path. The verdict comes from the vault checkout;
    neither runs or is read, and the test still fails: the work doesn't pass it."""
    marker = tmp_path / "PWNED"
    out = tmp_path / "out"

    def edit(c: Path) -> None:
        evil = tmp_path / "evil-common"
        (evil / "hooks").mkdir(parents=True)
        script = f"#!/bin/sh\necho ran >> {marker}\necho '{{}}' > {out}/harness_tests.json\n"
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
        (c / "tests" / "test_flag.py").write_text(FEATURE_TEST)  # the code isn't changed
        out.mkdir(parents=True, exist_ok=True)
        os.mkfifo(out / "harness_tests.json")

    clone = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    edit(clone)
    # the stand-in commits with git pinned, as the real harness does; what's
    # tested is vigild's side
    pins = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false"]
    env = {**os.environ, "GIT_COMMON_DIR": str(clone / ".git")}
    for args in (["add", "-A"], ["commit", "-qm", "w"]):
        subprocess.run(["git", *pins, *args], cwd=clone, check=True, env=env)
    bundle = ["bundle", "create", "-q", str(out / "result.bundle"), f"refs/heads/{BRANCH}"]
    git(clone, *bundle, f"^{base}")
    head = ws.import_result(REPO, TID, out, BRANCH, base, head=git(clone, "rev-parse", BRANCH))
    rec = _verify(ws, base, head)
    assert rec["after"]["outcome"] == "fail"
    assert not marker.exists()
    assert (out / "harness_tests.json").is_fifo()  # never opened, never replaced


# --- round 3, F1: the base's runner files in every run ----------------------------------------


def test_a_rewritten_test_script_runs_as_the_base_wrote_it(ws: Workspace, tmp_path: Path) -> None:
    """The reviewer's replay: `sh run_tests.sh`, rewritten to `exit 0`."""

    def edit(c: Path) -> None:
        (c / "tests" / "test_flag.py").write_text(FEATURE_TEST)
        (c / "run_tests.sh").write_text("exit 0\n")

    base, head = _session(ws, tmp_path, edit)
    rec = _verify(ws, base, head, "sh run_tests.sh")
    assert rec["after"]["outcome"] == "fail"  # the base's script ran the real tests
    assert rec["runner_config"]["pinned_to_base"] == ["run_tests.sh"]


def test_a_narrowed_package_script_runs_as_the_base_wrote_it(ws: Workspace, tmp_path: Path) -> None:
    """The ParkAgent version: package.json's test script narrowed to the new
    test would hide a regression in the old ones."""

    def edit(c: Path) -> None:
        _turn_on(c)
        (c / "tests" / "test_old.py").unlink()  # pretend it would fail now
        (c / "package.json").write_text('{"scripts": {"test": "pytest -q tests/test_flag.py"}}\n')

    base, head = _session(ws, tmp_path, edit)
    # stands in for `pnpm test`: run package.json's test script
    cmd = (
        'python3 -c "import json,subprocess,sys;'
        "sys.exit(subprocess.call(json.load(open('package.json'))['scripts']['test'],shell=True))\""
    )
    rec = _verify(ws, base, head, cmd)
    assert "package.json" in rec["runner_config"]["pinned_to_base"]
    assert not rec["ran"]["ok"]  # the base's script runs every test: head ran fewer
    assert rec["ran"]["missing_files"] == ["tests.test_old"]


def test_runner_files_come_from_the_base_even_when_the_spec_names_them(
    ws: Workspace, tmp_path: Path
) -> None:
    def edit(c: Path) -> None:
        _turn_on(c)
        (c / "conftest.py").write_text("raise SystemExit('the worker\\'s conftest ran')\n")

    base, head = _session(ws, tmp_path, edit)
    rec = _verify(ws, base, head)
    assert rec["runner_config"]["pinned_to_base"] == ["conftest.py"]
    assert rec["after"]["outcome"] == "pass"


# --- round 3: what ran, base against head -----------------------------------------------------


def test_an_added_skip_is_rejected(ws: Workspace, tmp_path: Path) -> None:
    def edit(c: Path) -> None:
        _turn_on(c)
        (c / "tests" / "test_old.py").write_text(
            "import pytest\n\n\n@pytest.mark.skip\ndef test_old():\n    assert 1 + 1 == 2\n\n\n"
            "def test_old_2():\n    assert True\n"
        )

    base, head = _session(ws, tmp_path, edit)
    rec = _verify(ws, base, head)
    assert rec["after"]["outcome"] == "pass"
    assert not rec["ran"]["ok"] and rec["ran"]["skipped"] == {"base": 0, "head": 1}


def test_an_added_xfail_is_rejected(ws: Workspace, tmp_path: Path) -> None:
    def edit(c: Path) -> None:
        _turn_on(c)
        (c / "tests" / "test_old.py").write_text(
            "import pytest\n\n\n@pytest.mark.xfail\ndef test_old():\n    assert 1 + 1 == 3\n\n\n"
            "def test_old_2():\n    assert True\n"
        )

    base, head = _session(ws, tmp_path, edit)
    rec = _verify(ws, base, head)
    assert not rec["ran"]["ok"] and rec["ran"]["xfail"] == {"base": 0, "head": 1}


def test_a_deleted_test_file_is_rejected(ws: Workspace, tmp_path: Path) -> None:
    def edit(c: Path) -> None:
        _turn_on(c)
        (c / "tests" / "test_old.py").unlink()

    base, head = _session(ws, tmp_path, edit)
    rec = _verify(ws, base, head)
    assert not rec["ran"]["ok"]
    assert rec["ran"]["missing_ids"] == ["tests.test_old::test_old", "tests.test_old::test_old_2"]


# --- round 3, F3: what a result means ---------------------------------------------------------


def test_an_unrelated_failure_at_before_is_not_must_fail_first(
    ws: Workspace, tmp_path: Path
) -> None:
    """The reviewer's assert-nothing replay: the new test asserts nothing, and
    "before" fails only because of another part of test_cmd."""

    def edit(c: Path) -> None:
        (c / "tests" / "test_flag.py").write_text("def test_flag():\n    pass\n")
        (c / "docs" / "feature-map.md").write_text("rate limit\n")

    base, head = _session(ws, tmp_path, edit)
    cmd = "pytest -q tests && grep -q 'rate limit' docs/feature-map.md"
    rec = _verify(ws, base, head, cmd)
    assert rec["before"]["outcome"] == "fail" and rec["after"]["outcome"] == "pass"
    assert rec["ids"]["checked"] is True and rec["ids"]["failing_before"] == []


def test_a_collection_error_at_before_is_unknown(ws: Workspace, tmp_path: Path) -> None:
    def edit(c: Path) -> None:
        (c / "tests" / "test_new.py").write_text(
            "from src.newmod import thing\n\n\ndef test_thing():\n    assert thing() == 1\n"
        )
        (c / "src" / "newmod.py").write_text("def thing():\n    return 1\n")

    base, head = _session(ws, tmp_path, edit)
    rec = _verify(ws, base, head, "pytest -q tests/test_new.py")
    assert rec["before"]["outcome"] == "unknown"  # pytest exit 2: collection error
    assert rec["after"]["outcome"] == "pass"


def test_zero_tests_through_a_pipe_is_unknown_at_head(ws: Workspace, tmp_path: Path) -> None:
    """`pnpm test 2>&1 | tail` that runs no test: pipefail carries the
    runner's exit, and "no tests" is not a pass."""
    base, head = _session(ws, tmp_path, _turn_on)
    rec = _verify(ws, base, head, "pytest -q -k no_such_test tests 2>&1 | tail -n 5", mff=False)
    assert rec["after"]["outcome"] == "unknown"


def test_a_runner_with_no_report_is_unknown_at_head(ws: Workspace, tmp_path: Path) -> None:
    def edit(c: Path) -> None:
        (c / "docs" / "feature-map.md").write_text("| rate limit | 10 |\n")

    base, head = _session(ws, tmp_path, edit)
    rec = _verify(ws, base, head, "grep -q 'rate limit' docs/feature-map.md")
    assert rec["after"]["outcome"] == "unknown" and "no test report" in rec["after"]["note"]
    assert rec["ids"] == {
        "checked": False,
        "note": "test ids not checked: the runner gave no report",
    }
    assert rec["ran"]["checked"] is False


def test_a_vitest_package_script_is_asked_for_a_report() -> None:
    pkg = {"server/package.json": '{"scripts": {"test": "vitest run"}}'}
    got = with_reports("pnpm -C server test 2>&1 | tail -n 50", pkg.get)
    assert got == (
        "pnpm -C server test 2>&1 --reporter=default --reporter=junit"
        " --outputFile.junit=/tmp/vigil-report/vitest-1.xml | tail -n 50"
    )  # bash takes words after a redirection; the pipe still gets everything
    assert with_reports("pnpm -C server lint", pkg.get) == "pnpm -C server lint"
    assert "--reporter=junit" in with_reports("npx vitest run test/a.test.ts")


@pytest.mark.parametrize(
    ("code", "timed_out", "want"),
    [
        (0, False, "pass"),
        (1, False, "fail"),
        (125, False, "unknown"),
        (127, False, "unknown"),
        (137, False, "unknown"),
        (None, True, "timeout"),
    ],
)
def test_outcomes(code: int | None, timed_out: bool, want: str) -> None:
    assert outcome(code, timed_out) == want


@pytest.mark.parametrize(
    ("cmd", "code", "output", "want"),
    [
        ("pytest -q", 2, "", "unknown"),
        ("pytest -q", 3, "", "unknown"),
        ("pytest -q", 4, "", "unknown"),
        ("pytest -q", 5, "", "unknown"),
        ("pytest -q", 1, "", "fail"),
        ("uv run pytest -q", 5, "", "unknown"),
        ("pnpm test", 1, "No test files found, exiting with code 1", "unknown"),
        ("pnpm test", 137, "", "unknown"),
        ("pnpm test", 139, "", "unknown"),
        ("grep -q x a", 2, "", "fail"),
    ],
)
def test_runner_exits_that_are_not_test_results(
    cmd: str, code: int, output: str, want: str
) -> None:
    assert judge(cmd, code, False, output) == want

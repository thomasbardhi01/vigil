"""#136: the verifier runs every AC's test command of the approved spec.md in the
after checkout; a command that selects no test, or fails, fails the task."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)
from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.harness import LocalTestRunner
from tests.test_verifier import KEY, REPO, TID, _session, _turn_on, ws  # noqa: F401
from vigild.jobs.acceptance import ac_commands, ac_errors, check_tests
from vigild.verifier import Verifier
from vigild.workspace import Workspace

SELECTS = "pytest -q tests -k test_flag"
NOTHING = "pytest -q tests -k after_commit"
FAILS = "pytest -q tests -k test_nope_fails"


def _verify(
    ws: Workspace, base: str, head: str, acs: list[tuple[str, list[str]]], runner: Any = None
) -> dict[str, Any]:
    return Verifier(ws, runner or LocalTestRunner(), host_key=KEY).verify(
        repo=REPO,
        image="img",
        task_id=TID,
        base_sha=base,
        head=head,
        test_cmd="pytest -q tests",
        must_fail_first=True,
        runner_config=["conftest.py", "package.json"],
        ac_commands=acs,
    )


def _spec(*criteria: str) -> str:
    return "# Spec\n\n## Acceptance criteria\n" + "".join(f"- {c}\n" for c in criteria)


def test_an_ac_command_that_selects_tests_and_passes_passes(ws: Workspace, tmp_path: Path) -> None:
    base, head = _session(ws, tmp_path, _turn_on)
    rec = _verify(ws, base, head, [(SELECTS, ["AC1"])])
    (run,) = rec["ac"]
    assert run["command"] == SELECTS and run["acs"] == ["AC1"]
    assert run["outcome"] == "pass" and run["selected"] == 1 and run["report"] is True
    assert ac_errors(rec) == []


def test_an_ac_command_that_selects_zero_tests_fails_naming_the_ac(
    ws: Workspace, tmp_path: Path
) -> None:
    base, head = _session(ws, tmp_path, _turn_on)
    rec = _verify(ws, base, head, [(NOTHING, ["AC2"])])
    assert rec["ac"][0]["selected"] == 0
    assert ac_errors(rec) == [f"AC2: `{NOTHING}` selected 0 tests"]
    spec = {"test_cmd": "pytest -q tests", "must_fail_first": True}
    assert f"AC2: `{NOTHING}` selected 0 tests" in check_tests(spec, rec)


def test_a_failing_ac_command_fails_the_task(ws: Workspace, tmp_path: Path) -> None:
    def edit(c: Path) -> None:
        _turn_on(c)
        (c / "tests" / "test_bad.py").write_text("def test_nope_fails():\n    assert False\n")

    base, head = _session(ws, tmp_path, edit)
    rec = _verify(ws, base, head, [(FAILS, ["AC3"])])
    assert rec["ac"][0]["outcome"] == "fail" and rec["ac"][0]["selected"] == 1
    (err,) = ac_errors(rec)
    assert err.startswith(f"AC3: `{FAILS}` did not pass")


def test_a_missing_report_counts_as_zero_tests() -> None:
    run = {"command": "x", "acs": ["AC1"], "outcome": "pass", "selected": 3, "report": False}
    assert ac_errors({"ac": [run]}) == ["AC1: `x` selected 0 tests"]


def test_two_acs_with_one_command_run_it_once(ws: Workspace, tmp_path: Path) -> None:
    spec = _spec(f"AC1: one. test: `{SELECTS}`", f"AC2: two. test: `{SELECTS}`")
    cmds = ac_commands(spec)
    assert cmds == [(SELECTS, ["AC1", "AC2"])]
    base, head = _session(ws, tmp_path, _turn_on)
    runner = LocalTestRunner()
    rec = _verify(ws, base, head, cmds, runner)
    assert [c["command"] for c in runner.calls].count(SELECTS) == 1
    assert rec["ac"][0]["acs"] == ["AC1", "AC2"]


def test_a_failure_names_every_ac_that_shares_the_command() -> None:
    run = {"command": "c", "acs": ["AC1", "AC2"], "outcome": "pass", "selected": 0, "report": True}
    assert ac_errors({"ac": [run]}) == ["AC1/AC2: `c` selected 0 tests"]


def test_commands_come_only_from_the_approved_spec(ws: Workspace, tmp_path: Path) -> None:
    """A worker's report, or a file it wrote claiming other commands, changes nothing:
    the commands are the spec.md text's, and the verifier takes only that list."""
    spec = _spec(f"AC1: one. test: `{NOTHING}`")

    def edit(c: Path) -> None:
        _turn_on(c)
        liar = _spec(f"AC1: one. test: `{SELECTS}`")
        (c / "spec.md").write_text(liar)
        (c / ".vigil").mkdir(exist_ok=True)
        (c / ".vigil" / "worker_report.json").write_text('{"ac": [["pytest -q tests", ["AC1"]]]}')

    base, head = _session(ws, tmp_path, edit)
    runner = LocalTestRunner()
    rec = _verify(ws, base, head, ac_commands(spec), runner)
    ran = [c["command"] for c in runner.calls]
    assert NOTHING in ran and SELECTS not in ran
    assert ac_errors(rec) == [f"AC1: `{NOTHING}` selected 0 tests"]


def test_a_command_the_spec_gate_refuses_is_not_run() -> None:
    spec = _spec("AC1: a. test: `echo ok`", "AC2: b. test: `pytest -q tests -k a & true`")
    assert ac_commands(spec) == []


def test_a_worker_of_several_runs_only_the_acs_it_names() -> None:
    spec = _spec("AC1: a. test: `pytest -q tests/a.py`", "AC2: b. test: `pytest -q tests/b.py`")
    assert ac_commands(spec, only={"AC2"}) == [("pytest -q tests/b.py", ["AC2"])]

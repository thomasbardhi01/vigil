"""Stage 3 acceptance, machine-checked on the host, in the vault, after the
worker exits. Test results come only from the verifier; it fails closed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.conftest import git
from tests.harness import finish_session
from vigild.contract.models import WorkerReport
from vigild.jobs.acceptance import check_worker
from vigild.workspace import Workspace

REPO, TID, BRANCH = "o/fixture", "fx-0001-w1", "vigil/fx-0001-w1"
CONTRACT: dict[str, Any] = {
    "task_id": TID,
    "job_id": "fx-0001",
    "spec": {
        "goal": "g",
        "test_cmd": "grep -q 'rate limit' docs/feature-map.md",
        "done_when": "d",
        "must_fail_first": True,
        "files_in_scope": ["docs/feature-map.md"],
    },
    "limits": {"max_cost_usd": 1.0},
}
TESTS_OK = {"before": {"outcome": "fail"}, "after": {"outcome": "pass"}, "source": "verifier"}


def _report(**kw: object) -> WorkerReport:
    base: dict[str, object] = {
        "task_id": TID, "job_id": "fx-0001", "test_before": "fail", "test_after": "pass",
        "files_changed": ["docs/feature-map.md"], "summary": "s",
        "self_check": {"test_failed_first": True, "outside_scope": [], "not_done": "-",
                       "reviewer_would_flag": "-", "could_delete": "-"},
        "provenance": "claude",
    }  # fmt: skip
    base.update(kw)
    return WorkerReport.model_validate(base)


@pytest.fixture
def ws(tmp_path: Path, fixture_repo: dict[str, Path]) -> Workspace:
    return Workspace(tmp_path / "d", remote_url=lambda r: str(fixture_repo["bare"]))


def _result(ws: Workspace, tmp_path: Path, extra: object = None) -> tuple[str, str]:
    c = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    (c / "docs" / "feature-map.md").write_text("# Feature map\nrate limit\n")
    if callable(extra):
        extra(c)
    r = finish_session(c, tmp_path / "out", branch=BRANCH, base_sha=base)
    return base, ws.import_result(REPO, TID, tmp_path / "out", BRANCH, base, head=r["head"])


def _check(
    ws: Workspace,
    base: str,
    head: str,
    *,
    contract: dict[str, Any] = CONTRACT,
    report: WorkerReport | None = None,
    tests: Any = TESTS_OK,
    cost: float = 0.2,
) -> list[str]:
    return check_worker(ws, REPO, base, head, contract, report or _report(), tests, cost=cost)


def test_clean_worker_passes(ws: Workspace, tmp_path: Path) -> None:
    assert _check(ws, *_result(ws, tmp_path)) == []


def test_test_must_fail_first(ws: Workspace, tmp_path: Path) -> None:
    base, head = _result(ws, tmp_path)
    passed_before = {**TESTS_OK, "before": {"outcome": "pass"}}
    assert any("verifier saw" in e for e in _check(ws, base, head, tests=passed_before))


def test_test_must_pass_after(ws: Workspace, tmp_path: Path) -> None:
    base, head = _result(ws, tmp_path)
    failed = {**TESTS_OK, "after": {"outcome": "fail"}}
    assert any("must pass" in e for e in _check(ws, base, head, tests=failed))


def test_the_reports_test_fields_are_ignored(ws: Workspace, tmp_path: Path) -> None:
    """The verifier decides; what the worker says about its tests doesn't."""
    base, head = _result(ws, tmp_path)
    liar = _report(test_before="pass", test_after="fail")
    assert _check(ws, base, head, report=liar) == []
    failed = {**TESTS_OK, "after": {"outcome": "fail"}}
    assert _check(ws, base, head, report=_report(), tests=failed)


# blocker 4: the record is required, comes from the verifier, and "unknown" is no pass
@pytest.mark.parametrize(
    "tests", [None, {}, {"before": {"outcome": "fail"}, "after": {"outcome": "pass"}}]
)
def test_a_missing_verifier_record_is_a_rejection(
    ws: Workspace, tmp_path: Path, tests: Any
) -> None:
    base, head = _result(ws, tmp_path)
    assert any("record is missing" in e for e in _check(ws, base, head, tests=tests))


@pytest.mark.parametrize("which", ["before", "after"])
@pytest.mark.parametrize("what", ["unknown", "timeout"])
def test_unknown_or_timeout_is_a_rejection(
    ws: Workspace, tmp_path: Path, which: str, what: str
) -> None:
    base, head = _result(ws, tmp_path)
    assert _check(ws, base, head, tests={**TESTS_OK, which: {"outcome": what}})


@pytest.mark.parametrize("cmd", [None, "", "   "])
def test_no_test_cmd_is_a_rejection(ws: Workspace, tmp_path: Path, cmd: str | None) -> None:
    """Review round 2, N2: an empty test_cmd used to accept with no record."""
    base, head = _result(ws, tmp_path)
    contract = {**CONTRACT, "spec": {**CONTRACT["spec"], "test_cmd": cmd}}
    assert any("no test_cmd" in e for e in _check(ws, base, head, contract=contract, tests=None))


def test_files_outside_scope_fail(ws: Workspace, tmp_path: Path) -> None:
    base, head = _result(ws, tmp_path, lambda c: (c / "README.md").write_text("x\n"))
    assert any("README.md" in e for e in _check(ws, base, head))


def test_a_weakened_test_fails(
    ws: Workspace, tmp_path: Path, fixture_repo: dict[str, Path]
) -> None:
    seed = fixture_repo["seed"]
    (seed / "tests").mkdir()
    (seed / "tests" / "test_x.py").write_text("def test_a():\n    assert 1\n    assert 2\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "t")
    git(seed, "push", "-q", "origin", "main")
    base, head = _result(
        ws,
        tmp_path,
        lambda c: (c / "tests" / "test_x.py").write_text("def test_a():\n    assert 1\n"),
    )
    contract = {
        **CONTRACT,
        "spec": {**CONTRACT["spec"], "files_in_scope": ["docs/feature-map.md", "tests/test_x.py"]},
    }
    assert any("weaken" in e for e in _check(ws, base, head, contract=contract))


def test_over_the_cost_limit_fails(ws: Workspace, tmp_path: Path) -> None:
    assert any("cost" in e for e in _check(ws, *_result(ws, tmp_path), cost=1.5))


def test_report_must_match_the_task(ws: Workspace, tmp_path: Path) -> None:
    base, head = _result(ws, tmp_path)
    assert any("task_id" in e for e in _check(ws, base, head, report=_report(task_id="other")))

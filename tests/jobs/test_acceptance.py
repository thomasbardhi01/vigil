"""Stage 3 acceptance, machine-checked on the host after the worker exits."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import git
from vigild.contract.models import WorkerReport
from vigild.jobs.acceptance import check_worker
from vigild.workspace import Workspace

CONTRACT = {
    "task_id": "fx-0001-w1",
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


def _report(**kw: object) -> WorkerReport:
    base: dict[str, object] = {
        "task_id": "fx-0001-w1",
        "job_id": "fx-0001",
        "test_before": "fail",
        "test_after": "pass",
        "files_changed": ["docs/feature-map.md"],
        "summary": "s",
        "self_check": {
            "test_failed_first": True,
            "outside_scope": [],
            "not_done": "-",
            "reviewer_would_flag": "-",
            "could_delete": "-",
        },
        "provenance": "claude",
    }
    base.update(kw)
    return WorkerReport.model_validate(base)


HARNESS_OK = {"before": {"outcome": "fail"}, "after": {"outcome": "pass"}}


@pytest.fixture
def clone(tmp_path: Path, fixture_repo: dict[str, Path]) -> Path:
    ws = Workspace(tmp_path / "d", remote_url=lambda r: str(fixture_repo["bare"]))
    c = ws.clone("o/fixture", "fx-0001-w1", branch="vigil/fx-0001-w1", base="main")
    (c / "docs" / "feature-map.md").write_text("# Feature map\nrate limit\n")
    git(c, "commit", "-qam", "w")
    return c


def test_clean_worker_passes(clone: Path) -> None:
    assert check_worker(clone, "main", CONTRACT, _report(), HARNESS_OK, cost=0.2) == []


def test_test_must_fail_first(clone: Path) -> None:
    errs = check_worker(clone, "main", CONTRACT, _report(test_before="pass"), HARNESS_OK, cost=0)
    assert any("fail first" in e for e in errs)
    harness = {"before": {"outcome": "pass"}, "after": {"outcome": "pass"}}
    errs = check_worker(clone, "main", CONTRACT, _report(), harness, cost=0)
    assert any("harness" in e for e in errs)


def test_test_must_pass_after(clone: Path) -> None:
    harness = {"before": {"outcome": "fail"}, "after": {"outcome": "fail"}}
    assert any(
        "pass" in e for e in check_worker(clone, "main", CONTRACT, _report(), harness, cost=0)
    )


def test_files_outside_scope_fail(clone: Path) -> None:
    (clone / "README.md").write_text("x\n")
    git(clone, "commit", "-qam", "x")
    errs = check_worker(clone, "main", CONTRACT, _report(), HARNESS_OK, cost=0)
    assert any("README.md" in e for e in errs)


def test_a_weakened_test_fails(clone: Path) -> None:
    (clone / "tests").mkdir()
    (clone / "tests" / "test_x.py").write_text("def test_a():\n    assert 1\n    assert 2\n")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "t")
    git(clone, "push", "-q", "origin", "HEAD:main")
    git(clone, "fetch", "-q", "origin")
    contract = {**CONTRACT, "spec": {**CONTRACT["spec"], "files_in_scope": ["tests/test_x.py"]}}  # type: ignore[dict-item]
    (clone / "tests" / "test_x.py").write_text("def test_a():\n    assert 1\n")
    git(clone, "commit", "-qam", "weaken")
    errs = check_worker(
        clone, "main", contract, _report(files_changed=["tests/test_x.py"]), HARNESS_OK, cost=0
    )
    assert any("weaken" in e for e in errs)


def test_over_the_cost_limit_fails(clone: Path) -> None:
    assert any(
        "cost" in e for e in check_worker(clone, "main", CONTRACT, _report(), HARNESS_OK, cost=1.5)
    )


def test_report_must_match_the_task(clone: Path) -> None:
    errs = check_worker(clone, "main", CONTRACT, _report(task_id="other"), HARNESS_OK, cost=0)
    assert any("task_id" in e for e in errs)

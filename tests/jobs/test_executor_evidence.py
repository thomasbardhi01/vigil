"""worker_report carries executor evidence from vigild's own records (#106).

Image digest, the three heads, the attempt lineage and a screened failure
diagnostic: built by vigild, never from what the worker wrote."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from typing import Any

from tests.jobs.test_coord_loop import World, _approve, _work, world  # noqa: F401
from vigild.contract.models import WorkerReport
from vigild.executors.base import SessionSpec
from vigild.jobs.artifacts import read_worker_report
from vigild.jobs.evidence import UNKNOWN_OUTPUT, failure_diagnostic

OLD_REPORT = {
    "task_id": "pa-0001-w1",
    "job_id": "pa-0001",
    "test_before": "fail",
    "test_after": "pass",
    "files_changed": ["a.py"],
    "summary": "did it",
    "self_check": {
        "test_failed_first": True,
        "outside_scope": [],
        "not_done": "nothing",
        "reviewer_would_flag": "x",
        "could_delete": "nothing",
    },
    "open_questions": [],
    "provenance": "claude",
}


def _stored(w: World, job: str) -> WorkerReport:
    art = w.store.get_artifact(job, "worker_report.json", f"{job}-w1")
    assert art is not None
    return WorkerReport.model_validate_json(art.content)


def test_the_stored_report_carries_vigilds_records(world: World) -> None:
    w = world
    job = _approve(w)
    task = f"{job}-w1"
    ex = _stored(w, job).executor
    assert ex is not None
    worker = next(s for s in w.standin.specs if s.task_id == task)
    sess = next(
        s for s in w.store.list_sessions(job) if s.task_id == task and s.role.value == "worker"
    )
    assert ex.image_digest == worker.image
    assert ex.base_head == w.runner.workspace.base_sha(task)
    assert ex.launch_head == sess.detail["session_base"] == sess.detail["launch_head"]
    assert ex.end_head == w.runner._task_head(task)
    assert ex.lineage is not None
    assert ex.lineage.mode == "fresh" and ex.lineage.parent_session_id is None
    assert ex.failure_diagnostic is None


def test_a_workers_own_executor_block_is_replaced(world: World) -> None:
    w = world

    def forge(spec: SessionSpec, task: dict[str, Any]) -> None:
        _work(spec.clone, task["spec"]["files_in_scope"][0])
        d = spec.clone / ".vigil" / spec.job_id / str(spec.task_id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "worker_report.json").write_text(
            json.dumps(
                {
                    **OLD_REPORT,
                    "task_id": spec.task_id,
                    "job_id": spec.job_id,
                    "executor": {"image_digest": "sha256:forged", "base_head": "f" * 40},
                }
            )
        )

    w.standin.worker_edit = forge
    job = _approve(w)
    ex = _stored(w, job).executor
    assert ex is not None and ex.image_digest != "sha256:forged"
    assert ex.base_head == w.runner.workspace.base_sha(f"{job}-w1")


def test_a_classified_failure_is_redacted_and_capped() -> None:
    secret = "sk-ant-api03-" + "A1b2C3d4" * 6
    out = failure_diagnostic("failed", 137, f"killed: out of budget cap {secret} " + "x" * 5000)
    assert out is not None
    assert len(out.encode()) <= 2000
    assert secret not in out and "[redacted]" in out
    assert out.startswith("out of cap")


def test_each_known_failure_kind_is_named() -> None:
    assert (failure_diagnostic("timeout", None, "") or "").startswith("timeout")
    assert (failure_diagnostic("failed", 3, "guard not loaded") or "").startswith("crash (exit 3)")
    assert (failure_diagnostic("failed", None, "request refused by gateway") or "").startswith(
        "refused"
    )


def test_unclassified_output_is_withheld() -> None:
    secret = "ghp_" + "Z9y8X7w6" * 5
    out = failure_diagnostic("failed", None, f"weird thing {secret}")
    assert out == UNKNOWN_OUTPUT == "withheld (unknown output)"
    assert failure_diagnostic("done", 0, "fine") is None


def test_a_planted_secret_in_multibyte_output_does_not_survive() -> None:
    secret = "ghp_" + "Z9y8X7w6" * 5
    out = failure_diagnostic("failed", 1, "é" * 1999 + secret)
    assert out is not None and secret not in out and len(out.encode()) <= 2000


def test_a_report_stored_before_106_still_loads(tmp_path: Any) -> None:
    assert WorkerReport.model_validate(OLD_REPORT).executor is None
    d = tmp_path / ".vigil" / "pa-0001" / "pa-0001-w1"
    d.mkdir(parents=True)
    (d / "worker_report.json").write_text(json.dumps(OLD_REPORT))
    assert read_worker_report(tmp_path, "pa-0001", "pa-0001-w1").executor is None

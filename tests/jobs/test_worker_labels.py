"""A job's labels reach a worker whose plan entry has no `labels` key (#179)."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

from typing import Any

import pytest

from tests.jobs.test_coord_loop import World, world  # noqa: F401
from tests.jobs.test_coord_routing import _submit
from vigild.contract.models import WorkerContract
from vigild.router.rules import route


def _worker(job: str, **extra: Any) -> WorkerContract:
    return WorkerContract.model_validate(
        {
            "task_id": f"{job}-w1",
            "goal": "add tests",
            "why": "AC1",
            "value": 3,
            "risk": 1,
            "size": "S",
            "test_cmd": "pytest -q tests/test_x.py",
            "done_when": "AC1 holds",
            "files_in_scope": ["tests/test_x.py"],
            **extra,
        }
    )


def _task(w: World, job: str, worker: WorkerContract, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(w.runner, "_has_existing_tests", lambda *a: True)
    j = w.store.get_job(job)
    return w.runner._task(job, j.repo, j.base, j.source, worker)


def test_a_worker_without_labels_inherits_the_jobs_and_routes_rule6(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _submit(world, labels=["tests"])
    task = _task(world, job, _worker(job), monkeypatch)
    assert task.labels == ["tests"]
    assert route(task, world.runner.cfg).tier_reason.startswith(
        "rule6:label:tests+size:S+tests-in-scope"
    )


def test_a_worker_with_its_own_labels_keeps_them(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _submit(world, labels=["tests"])
    task = _task(world, job, _worker(job, labels=["docs"]), monkeypatch)
    assert task.labels == ["docs"]


def test_a_worker_with_empty_labels_does_not_inherit(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _submit(world, labels=["tests"])
    task = _task(world, job, _worker(job, labels=[]), monkeypatch)
    assert task.labels == []
    assert route(task, world.runner.cfg).tier_reason.startswith("rule9:default")


def test_a_job_without_labels_changes_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _submit(world)
    task = _task(world, job, _worker(job), monkeypatch)
    assert task.labels == []

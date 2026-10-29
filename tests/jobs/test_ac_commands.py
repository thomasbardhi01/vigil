"""#136 in the runner world: the AC test commands of the approved spec.md run in the
after checkout, and one that selects no test fails the task at acceptance."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)
from __future__ import annotations

import json
from typing import Any

from tests.jobs.test_coord_loop import (
    SPEC,
    World,
    _approve,
    _failure_item,
    _work,
    plan,
    world,  # noqa: F401
)
from vigild.executors.base import SessionSpec

AC2 = "pytest -q tests/test_runbook.py"
NOMATCH = "pytest -q tests/test_runbook.py -k never_matches_anything"


def _edit(spec: SessionSpec, task: dict[str, Any]) -> None:
    _work(spec.clone, task["spec"]["files_in_scope"][0])


def test_an_ac_whose_selector_matches_no_test_fails_its_task_at_acceptance(world: World) -> None:
    w = world
    assert AC2 in SPEC
    w.standin.coord_drafts = [lambda j: (SPEC.replace(AC2, NOMATCH), plan(j))]
    w.standin.worker_edit = _edit
    job = _approve(w)
    assert w.store.get_task(f"{job}-w1").state != "failed"  # AC1 selects and passes
    assert w.store.get_task(f"{job}-w2").state == "failed"
    body = json.dumps(_failure_item(w, job)["body"])
    assert "stage 3 acceptance failed" in body
    assert f"AC2: `{NOMATCH}` selected 0 tests" in body
    assert f"vigil/{job}-w2" not in [p["head"] for p in w.publisher.prs]
    rec = json.loads(w.store.get_artifact(job, "tests.json", task_id=f"{job}-w2").content)
    assert rec["ac"][0]["selected"] == 0 and rec["ac"][0]["acs"] == ["AC2"]


def test_passing_ac_commands_change_nothing_for_a_good_job(world: World) -> None:
    w = world
    w.standin.worker_edit = _edit
    job = _approve(w)
    rec = json.loads(w.store.get_artifact(job, "tests.json", task_id=f"{job}-w1").content)
    assert [r["acs"] for r in rec["ac"]] == [["AC1"]]  # w1 names AC1 only
    assert rec["ac"][0]["selected"] >= 1 and rec["ac"][0]["outcome"] == "pass"
    assert f"vigil/{job}-w1" in [p["head"] for p in w.publisher.prs]

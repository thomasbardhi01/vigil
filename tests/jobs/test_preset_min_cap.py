"""#79 (b): a per-preset minimum task cap, at the spec gate and at dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.conftest import auth
from tests.jobs.test_coord_loop import REPO, World, _request
from tests.jobs.test_coord_loop import world as world
from tests.jobs.test_round2_runner import _inbox, _pages, assert_actionable
from tests.scheduler.test_fleet import _doc_work, plan_n, spec_n
from vigild import config as config_mod
from vigild.config import Config
from vigild.router.rules import min_cap_problem

JOB = "pa-0001"


def _plan(cap: float) -> str:
    return plan_n(JOB, 1).replace('"max_cost_usd": 1.0', f'"max_cost_usd": {cap}')


def test_the_gate_refuses_a_sonnet_task_under_the_minimum(world: World) -> None:
    errors = world.runner.jobs.gate_drafts(REPO, spec_n(1), _plan(0.30), "main")
    (e,) = [e for e in errors if "minimum" in e]
    assert f"{JOB}-w1" in e and "claude-sonnet" in e and "0.30" in e and "0.60" in e


def test_the_gate_passes_a_sonnet_task_at_the_minimum(world: World) -> None:
    assert world.runner.jobs.gate_drafts(REPO, spec_n(1), _plan(0.60), "main") == []


def test_a_preset_without_a_minimum_passes(cfg: Config) -> None:
    assert cfg.preset("tower-qwen").min_task_usd is None
    assert min_cap_problem(cfg, "t1", "tower-qwen", 0.0) is None
    assert min_cap_problem(cfg, "t1", "claude-sonnet", 0.60) is None


def test_dispatch_starts_no_session_for_a_held_sub_minimum_task(world: World) -> None:
    w = world
    w.runner.jobs._gate = lambda *a, **k: []  # type: ignore[method-assign]  # approved before the rule
    w.standin.coord_drafts = [lambda j: (spec_n(1), _plan(0.30))]
    w.standin.worker_edit = _doc_work()
    job = _request(w)
    (item,) = _inbox(w)["specs"]
    r = w.client.post(f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={})
    assert r.status_code == 200, r.text
    page = assert_actionable(w, job)
    assert page["body"]["actions"] == ["replan", "abandon"]
    assert page["body"]["kind"] == "min_task_cap"
    assert "claude-sonnet" in str(page["body"]) and "0.6" in str(page["body"])
    assert len(_pages(w, job)) == 1
    assert not [s for s in w.store.list_sessions(job) if s.role.value == "worker"]


def test_min_task_usd_loads_and_an_unknown_key_still_fails(tmp_path: Path) -> None:
    c = config_mod.load()
    assert c.preset("claude-sonnet").min_task_usd == 0.60
    raw = c.backends.model_dump()
    raw["presets"]["claude-sonnet"]["min_task_usdd"] = 1
    with pytest.raises(ValidationError):
        type(c.backends).model_validate(raw)

"""#121: no session that can't afford one call at the gateway's floor, and the
CLI's stderr kept. A retry or a fix round on the dregs of a task's cap starts no
container, books no reservation, and pages with replan and abandon only; the
repo's failure count doesn't move. A worker whose CLI exits non-zero keeps the
redacted tail of its stderr on the session and in the page."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.conftest import auth
from tests.jobs.test_coord_loop import (  # noqa: F401
    World,
    _approve,
    _failure_item,
    _flaky,
    _spend,
    world,
)
from tests.jobs.test_fix_with_findings import _fix, _ready, _workers
from vigild.breakers import Kind
from vigild.executors.base import EventSink, ExecOutcome, SessionSpec
from vigild.gateway.service import CHARS_PER_TOKEN, MIN_OUTPUT_TOKENS, worst_case_usd
from vigild.jobs.model import Role
from vigild.metering.prices import PriceTable

REASON = "under the floor for one call"


def _failures(w: World, repo: str = "o/fixture") -> int:
    b = w.runner.breakers._row(Kind.REPO_FAILURES, f"repo:{repo}")
    return b.count if b else 0


def _drain(w: World, task: str, left: float) -> None:
    """Spend the task's cap down to `left`, as an aborted session would have, after a
    call whose 20,000 input tokens are what any next call carries at least."""
    w.store.x(
        "INSERT INTO model_calls (session_id, task_id, job_id, purpose, provider, model,"
        " tokens_in, tokens_out, tokens_cache_read, tokens_cache_write_5m,"
        " tokens_cache_write_1h, cost_usd, ts, provenance) VALUES"
        " (NULL,?,NULL,'session','anthropic','claude-sonnet-5-5',20000,1,0,0,0,0.0,?,'local')",
        (task, "2026-10-29T00:00:00+00:00"),
    )
    _, _, now = w.runner.remaining(task)
    rid = w.budget.reserve(session_id=None, task_id=task, amount=now, purpose="worker")
    w.budget.settle(rid, now - left)


def _out_of_cap_page(w: World, job: str) -> dict[str, Any]:
    item = _failure_item(w, job)
    assert item["body"]["actions"] == ["replan", "abandon"]
    assert item["body"]["resumable"] is False
    return item  # type: ignore[no-any-return]


def test_the_floor_is_the_gateways_own_arithmetic(world: World) -> None:
    w = world
    prices = PriceTable(w.runner.cfg.prices)
    job = _approve(w)
    task = f"{job}-w1"
    model = w.runner.cfg.preset(w.store.get_task(task).backend_preset or "").model or ""
    # no call yet: only the output the gateway will not go under
    assert w.runner.call_floor_usd(task) == pytest.approx(
        worst_case_usd(prices, model, 0, MIN_OUTPUT_TOKENS)
    )
    _drain(w, task, 1.0)  # then the smallest input a call of the task has had counts too
    assert w.runner.call_floor_usd(task) == pytest.approx(
        worst_case_usd(prices, model, 20_000 * CHARS_PER_TOKEN, MIN_OUTPUT_TOKENS)
    )


def test_a_retry_on_the_dregs_starts_no_session_and_pages_replan_and_abandon(
    world: World,
) -> None:
    w = world
    w.standin.worker_edit = _flaky({"w1"})
    job = _approve(w)
    task = f"{job}-w1"
    item = _failure_item(w, job)
    assert item["body"]["actions"] == ["retry", "replan", "abandon"]
    assert _failures(w) == 1
    _drain(w, task, 0.06)  # under the floor for one call
    sessions = len(_workers(w, "w1"))
    rows = len(w.store.q("SELECT 1 FROM reservations WHERE task_id=?", (task,)))
    ledger = len(w.store.q("SELECT 1 FROM ledger WHERE task_id=?", (task,)))

    r = w.client.post(f"/api/inbox/{item['id']}/retry", headers=auth(w.tokens.admin))
    assert r.status_code == 200, r.text

    assert len(_workers(w, "w1")) == sessions  # no container, no session
    assert len(w.store.q("SELECT 1 FROM reservations WHERE task_id=?", (task,))) == rows
    assert len(w.store.q("SELECT 1 FROM ledger WHERE task_id=?", (task,))) == ledger
    assert w.budget.open_today() == 0
    page = _out_of_cap_page(w, job)
    why = page["body"]["tasks"][task]
    assert why["error"].startswith("out of cap: $0.06 left, under the floor for one call ($0.")
    assert REASON in why["error"] and why["error"].endswith(
        "replan to give a fresh worker its own cap"
    )
    assert _failures(w) == 1  # a budget outcome, not a repo failure


def test_a_fix_round_on_the_dregs_does_the_same(world: World) -> None:
    w = world
    job, item = _ready(w)
    task = f"{job}-w1"
    _drain(w, task, 0.06)
    rows = len(w.store.q("SELECT 1 FROM reservations WHERE task_id=?", (task,)))
    before = _failures(w)

    r = _fix(w, item["id"], task_id=task, findings=["audit:0"])
    if r.status_code != 200:  # diagnostic (CI-only 409 on #162): say what the task holds
        from vigild.jobs.fixfindings import selectable

        arts = {
            n: (a.content[:300] if (a := w.store.get_artifact(job, n, task)) else None)
            for n in ("review.json", "audit.json")
        }
        evs = [
            (e["type"], e["data"][:160])
            for e in w.store.q(
                "SELECT type, data FROM events WHERE job_id=? ORDER BY id DESC LIMIT 12", (job,)
            )
        ]
        raise AssertionError(
            f"{r.text}\nselectable={selectable(w.store, job, task)}\nartifacts={arts}\nevents={evs}"
        )

    assert len(_workers(w, "w1")) == 1  # the first session only
    assert len(w.store.q("SELECT 1 FROM reservations WHERE task_id=?", (task,))) == rows
    page = _out_of_cap_page(w, job)
    assert REASON in page["body"]["tasks"][task]["error"]
    assert _failures(w) == before


def test_with_enough_cap_the_run_goes_on_as_today(world: World) -> None:
    w = world
    w.standin.worker_edit = _flaky({"w1"})
    w.standin.on_session = _spend(w, 15_000)  # $0.30; $1.70 left
    job = _approve(w)
    item = _failure_item(w, job)
    assert item["body"]["actions"] == ["retry", "replan", "abandon"]
    assert w.runner.call_floor_usd(f"{job}-w1") < 1.70
    r = w.client.post(f"/api/inbox/{item['id']}/retry", headers=auth(w.tokens.admin))
    assert r.status_code == 200, r.text
    assert len(_workers(w, "w1")) == 2


def test_a_worker_whose_cli_exits_keeps_the_redacted_stderr_tail(world: World) -> None:
    w = world
    secret = "ghs_" + "a1B2c3D4e5F6g7H8i9J0"
    noise = "x" * 3000
    stderr = f"{noise}\nthread 'main' panicked: pids\nGITHUB_TOKEN={secret}\n"
    real = w.standin.run

    def run(spec: SessionSpec, token: str, sink: EventSink) -> ExecOutcome:
        if spec.role is Role.WORKER and str(spec.task_id).endswith("w1"):
            return ExecOutcome(
                "failed", 4, {"status": "failed", "error": "ProcessError: exit -6",
                              "cli_stderr_tail": stderr[-2000:]},
                "ProcessError: exit -6",
            )  # fmt: skip
        return real(spec, token, sink)

    w.standin.run = run  # type: ignore[method-assign]
    job = _approve(w)
    task = f"{job}-w1"
    (s,) = [x for x in w.store.list_sessions(job) if x.task_id == task]
    tail = s.detail["cli_stderr_tail"]
    assert "panicked: pids" in tail and len(tail.encode()) <= 2000
    assert secret not in tail and "[redacted]" in tail
    body = _failure_item(w, job)["body"]
    assert "panicked: pids" in body["tasks"][task]["cli_stderr_tail"]
    assert secret not in json.dumps(body)

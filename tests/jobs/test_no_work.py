"""No work, never green (#102): a worker session with no `model_calls` row can't
publish, and no report counts it as $0."""

from __future__ import annotations

import json

from tests.jobs.test_coord_loop import World, _approve, _failure_item, _spend
from tests.jobs.test_coord_loop import world as world
from vigild.db import Store
from vigild.jobs.batch import batch_view
from vigild.jobs.model import Role
from vigild.jobs.tree import job_tree
from vigild.kpis import compute

NOW = "2026-10-28T00:00:00+00:00"


def test_a_session_with_no_rows_cannot_reach_pr_open_and_the_job_is_paged(world: World) -> None:
    w = world
    w.standin.meter_workers = False  # the session ran and wrote work, but never called a model
    job = _approve(w)
    assert w.publisher.prs == []
    assert {t.state for t in w.store.list_tasks(job)} == {"failed"}
    assert w.store.get_job(job).state.value == "blocked"
    item = _failure_item(w, job)
    assert item["body"]["actions"] == ["retry", "replan", "abandon"]
    assert "session did no metered work" in json.dumps(item["body"]["tasks"])
    assert w.store.q("SELECT 1 FROM events WHERE type='pr_open'") == []


def test_a_session_with_one_row_publishes_as_today(world: World) -> None:
    w = world
    w.standin.on_session = _spend(w, 1_000)
    job = _approve(w)
    assert len(w.publisher.prs) == 2
    assert {t.state for t in w.store.list_tasks(job)} <= {"pr_open", "reviewed"}
    assert w.store.get_job(job).state.value != "blocked"


def _session(store: Store, job: str, sid: str, cost: float, rows: int) -> None:
    store.x(
        "INSERT INTO sessions (id, job_id, role, status, created_at, ended_at, cost_usd,"
        " provenance) VALUES (?,?,?,?,?,?,?,?)",
        (sid, job, Role.WORKER.value, "done", NOW, NOW, cost, "local"),
    )
    store.x(
        "INSERT INTO ledger (session_id, amount_usd, day, month, ts) VALUES (?,?,?,?,?)",
        (sid, cost, "2026-10-28", "2026-10", NOW),
    )
    for _ in range(rows):
        store.x(
            "INSERT INTO model_calls (session_id, job_id, purpose, provider, model, tokens_in,"
            " tokens_out, tokens_cache_read, tokens_cache_write_5m, tokens_cache_write_1h,"
            " cost_usd, ts, provenance) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, job, "session", "anthropic", "m", 1, 1, 0, 0, 0, cost, NOW, "local"),
        )


NOTE = "cost unknown; booked at reservation $0.25"
UNKNOWN = [{"session_id": "s-none", "note": NOTE}]


def test_the_job_tree_lists_a_no_row_session_apart_and_keeps_its_booking(store: Store) -> None:
    job = store.create_job(repo="o/r", base="main", title="t", request="r", notes=[])
    _session(store, job.id, "s-ok", 0.5, 1)
    _session(store, job.id, "s-none", 0.25, 0)
    tree = job_tree(store, job.id)
    nodes = {n["id"]: n for n in tree["sessions"]}
    assert nodes["s-none"]["cost_usd"] == 0.25 and nodes["s-none"]["cost_missing"] is True
    assert nodes["s-ok"]["cost_usd"] == 0.5 and nodes["s-ok"]["cost_missing"] is False
    assert tree["job"]["cost_usd"] == 0.75
    assert tree["job"]["cost_unknown_sessions"] == UNKNOWN


def test_the_batch_roll_up_lists_a_no_row_session_apart_and_keeps_its_booking(
    store: Store,
) -> None:
    batch, (job_id,) = store.create_batch(
        "b", [{"repo": "o/r", "base": "main", "title": "t", "request": "r", "notes": []}]
    )
    _session(store, job_id, "s-ok", 0.5, 1)
    _session(store, job_id, "s-none", 0.25, 0)
    out = batch_view(store, batch)
    assert out["jobs"][0]["spent_usd"] == 0.75
    assert out["jobs"][0]["cost_unknown_sessions"] == UNKNOWN
    assert out["cost"]["spent_usd"] == 0.75
    assert out["cost"]["cost_unknown_sessions"] == UNKNOWN


def test_the_kpis_list_a_no_row_session_apart_and_keep_its_booking(store: Store) -> None:
    job = store.create_job(repo="o/r", base="main", title="t", request="r", notes=[])
    for f, t in (("building", "in_review"), ("in_review", "ready"), ("ready", "merged")):
        store.add_event("state", {"from": f, "to": t}, "human", job_id=job.id)
    _session(store, job.id, "s-ok", 1.5, 1)
    _session(store, job.id, "s-none", 0.25, 0)
    store.x("UPDATE sessions SET pr_url='https://x/1' WHERE id='s-ok'")
    k = compute(store)
    assert k["cost_per_merged_pr"] == 1.75
    assert k["cost_unknown_sessions"] == UNKNOWN


def test_no_reservation_in_the_ledger_notes_zero(store: Store) -> None:
    job = store.create_job(repo="o/r", base="main", title="t", request="r", notes=[])
    _session(store, job.id, "s-none", 0.0, 0)
    store.x("DELETE FROM ledger")
    assert job_tree(store, job.id)["job"]["cost_unknown_sessions"] == [
        {"session_id": "s-none", "note": "cost unknown; booked at reservation $0.00"}
    ]

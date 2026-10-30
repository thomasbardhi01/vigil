"""The owner's republish of a failed task's verified head (owner, 2026-10-30):
`POST /api/inbox/{id}/republish` with {"task_id"}. vigild checks the verifier's record
against the vault ref, then publishes that head through the normal publish path: no
worker session, no reservation, no verifier run. The coord token can't."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from typing import Any

from tests.conftest import git
from tests.jobs.test_coord_loop import (
    World,
    _approve,
    _events,
    _failure_item,
    auth,
    world,  # noqa: F401
)
from tests.jobs.test_republish import _refuse_w1_once, _w1_calls


def _failed(w: World) -> tuple[str, str, dict[str, Any]]:
    """A job whose w1 was verified and accepted, then refused at publish: failed, paged."""
    _refuse_w1_once(w)
    job = _approve(w)
    tid = f"{job}-w1"
    assert w.store.get_task(tid).state == "failed"
    return job, tid, _failure_item(w, job)


def _post(w: World, item: int, tid: str | None, token: str | None = None) -> Any:
    return w.client.post(
        f"/api/inbox/{item}/republish",
        headers=auth(token or w.tokens.admin),
        json={"task_id": tid},
    )


def _record(w: World, job: str, tid: str) -> dict[str, Any]:
    art = w.store.get_artifact(job, "tests.json", tid)
    assert art is not None
    return json.loads(art.content)  # type: ignore[no-any-return]


def _vault_ref(w: World, job: str, tid: str, sha: str) -> None:
    repo = w.store.get_job(job).repo
    git(w.runner.workspace.vault(repo), "update-ref", f"refs/vigil/{tid}", sha)


def test_a_head_that_differs_from_the_vault_ref_is_a_409_naming_both(world: World) -> None:
    w = world
    job, tid, item = _failed(w)
    after = _record(w, job, tid)["after"]["sha"]
    other = w.runner.workspace.base_sha(tid)
    assert other != after
    _vault_ref(w, job, tid, other)
    prs, events = len(w.publisher.prs), len(_events(w, "republish"))
    r = _post(w, item["id"], tid)
    assert r.status_code == 409, r.text
    assert after in r.text and other in r.text
    assert len(w.publisher.prs) == prs and len(_events(w, "republish")) == events
    assert w.store.get_task(tid).state == "failed"
    assert w.store.get_inbox_item(item["id"]).status == "open"


def test_a_matching_head_is_republished_with_no_session(world: World) -> None:
    w = world
    job, tid, item = _failed(w)
    after = _record(w, job, tid)["after"]["sha"]
    reservations = w.store.q("SELECT id FROM reservations WHERE task_id=?", (tid,))
    r = _post(w, item["id"], tid)
    assert r.status_code == 200, r.text
    assert w.store.get_task(tid).state in ("pr_open", "reviewed")
    assert _w1_calls(w, job) == 1  # no worker session started
    assert w.store.q("SELECT id FROM reservations WHERE task_id=?", (tid,)) == reservations
    (rep,) = [e for e in _events(w, "republish") if e["task_id"] == tid]
    (opened,) = [e for e in _events(w, "pr_open") if e["task_id"] == tid]
    assert rep["head"] == after == opened["head"]
    assert rep["inbox_item_id"] == item["id"] and rep["result"] == opened["pr_url"]
    assert f"vigil/{job}-w1" in [p["head"] for p in w.publisher.prs]
    assert w.store.get_inbox_item(item["id"]).status == "resolved"


def test_the_coord_token_gets_a_403_and_nothing_changes(world: World) -> None:
    w = world
    _job, tid, item = _failed(w)
    prs = len(w.publisher.prs)
    r = _post(w, item["id"], tid, w.tokens.coord)
    assert r.status_code == 403, r.text
    assert w.store.get_task(tid).state == "failed"
    assert len(w.publisher.prs) == prs and not _events(w, "republish")
    assert w.store.get_inbox_item(item["id"]).status == "open"
    for t in (w.tokens.read, w.tokens.heartbeat):
        if t:
            assert _post(w, item["id"], tid, t).status_code == 403


def test_no_verifier_record_is_a_409(world: World) -> None:
    w = world
    _job, tid, item = _failed(w)
    w.store.x("DELETE FROM artifacts WHERE name='tests.json' AND task_id=?", (tid,))
    r = _post(w, item["id"], tid)
    assert r.status_code == 409, r.text
    assert w.store.get_task(tid).state == "failed" and not _events(w, "republish")


def test_a_record_without_an_after_sha_is_a_409(world: World) -> None:
    w = world
    job, tid, item = _failed(w)
    rec = _record(w, job, tid)
    rec["after"].pop("sha")
    w.store.add_artifact(
        job, "tests.json", json.dumps(rec), w.store.get_job(job).provenance, task_id=tid
    )
    assert _post(w, item["id"], tid).status_code == 409
    assert not _events(w, "republish")


def test_a_page_that_is_not_a_failed_task_page_is_refused(world: World) -> None:
    w = world
    _job, tid, item = _failed(w)
    assert _post(w, item["id"], "vi-9999-w9").status_code == 409  # not on this page
    spec = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()
    other = [q for q in spec["questions"] if q["body"].get("kind") != "worker_failed"]
    for q in other:
        assert _post(w, q["id"], tid).status_code == 409
    assert _post(w, 999999, tid).status_code == 404
    assert not _events(w, "republish")

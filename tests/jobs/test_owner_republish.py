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
    _request,
    auth,
    world,  # noqa: F401
)
from tests.jobs.test_republish import _refuse_w1_once, _w1_calls
from vigild.provenance import Provenance


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
    job, tid, item = _failed(w)
    assert _post(w, item["id"], "vi-9999-w9").status_code == 409  # not among the page's tasks
    assert _post(w, item["id"], None).status_code == 409
    other = [
        w.store.create_inbox_item(
            "questions", kind, job, f"{kind} page", body, Provenance.HUMAN, own_job=True
        ).id
        for kind, body in (
            ("ask_coord", {"question": "?", "task_id": tid}),
            ("budget", {"kind": "budget", "tasks": {}, "actions": ["abandon"]}),
        )
    ]
    assert other, "the case list would be empty"
    for qid in other:
        assert _post(w, qid, tid).status_code == 409
    assert _post(w, 999999, tid).status_code == 404
    assert not _events(w, "republish") and not _events(w, "owner_republish")


def test_a_task_of_another_job_is_refused(world: World) -> None:
    w = world
    _job, tid, item = _failed(w)
    other = _request(w)  # a second job, still waiting for its spec's approval
    w.store.x("UPDATE tasks SET job_id=? WHERE id=?", (other, tid))
    r = _post(w, item["id"], tid)
    assert r.status_code == 409, r.text
    assert not _events(w, "owner_republish")


def test_a_task_that_is_not_failed_is_refused(world: World) -> None:
    w = world
    _job, tid, item = _failed(w)
    w.store.x("UPDATE tasks SET state='pr_open' WHERE id=?", (tid,))
    r = _post(w, item["id"], tid)
    assert r.status_code == 409, r.text
    assert not _events(w, "owner_republish")


def _verdicts(w: World, tid: str) -> list[dict[str, Any]]:
    return [e for e in _events(w, "acceptance") if e["task_id"] == tid]


def test_the_normal_path_records_the_acceptance_verdict(world: World) -> None:
    w = world
    job, tid, _item = _failed(w)
    (ok,) = _verdicts(w, tid)
    assert ok["accepted"] is True and ok["errors"] == []
    assert ok["head"] == _record(w, job, tid)["after"]["sha"] and ok["task"] == tid


def test_a_failed_acceptance_is_recorded_and_never_republished(world: World) -> None:
    """tests.json is written before stage 3: the verifier's record and a vault ref aren't
    proof the head was accepted; the stage's own verdict is."""
    from tests.jobs.test_coord_loop import _flaky

    w = world
    w.standin.worker_edit = _flaky({"w1"})
    job = _approve(w)
    tid = f"{job}-w1"
    item = _failure_item(w, job)
    assert "stage 3 acceptance failed" in json.dumps(item["body"]["tasks"])
    after = _record(w, job, tid)["after"]["sha"]
    assert after == w.runner.workspace.task_ref(w.store.get_job(job).repo, tid)
    first = _verdicts(w, tid)[0]
    assert first["accepted"] is False and first["head"] == after and first["errors"]
    r = _post(w, item["id"], tid)
    assert r.status_code == 409 and f"acceptance refused {after}" in r.text, r.text
    assert not _events(w, "owner_republish")
    assert f"vigil/{job}-w1" not in [p["head"] for p in w.publisher.prs]


def test_the_latest_verdict_for_the_verified_head_decides(world: World) -> None:
    w = world
    job, tid, item = _failed(w)
    a = _record(w, job, tid)["after"]["sha"]
    b = w.runner.workspace.base_sha(tid)  # a second import, B
    assert a != b
    rec = _record(w, job, tid)
    rec["after"]["sha"] = b
    w.store.add_artifact(job, "tests.json", json.dumps(rec), Provenance.HUMAN, task_id=tid)
    _vault_ref(w, job, tid, b)
    # B verified but not yet judged: A's pass doesn't carry over
    r = _post(w, item["id"], tid)
    assert r.status_code == 409 and f"no acceptance verdict recorded for {b}" in r.text, r.text
    w.store.add_event(
        "acceptance",
        {"task": tid, "head": b, "accepted": False, "errors": ["out of scope: x"]},
        Provenance.HUMAN,
        job_id=job,
        task_id=tid,
    )
    r = _post(w, item["id"], tid)
    assert r.status_code == 409 and f"acceptance refused {b}: out of scope: x" in r.text, r.text
    assert not _events(w, "owner_republish")
    w.store.add_event(
        "acceptance",
        {"task": tid, "head": b, "accepted": True, "errors": []},
        Provenance.HUMAN,
        job_id=job,
        task_id=tid,
    )
    assert w.runner._owner_inputs(job, tid)["head"] == b


def test_a_task_with_no_acceptance_verdict_is_a_409(world: World) -> None:
    w = world
    job, tid, item = _failed(w)
    after = _record(w, job, tid)["after"]["sha"]
    w.store.x("DELETE FROM events WHERE type='acceptance' AND task_id=?", (tid,))
    r = _post(w, item["id"], tid)
    assert r.status_code == 409 and f"no acceptance verdict recorded for {after}" in r.text
    assert not _events(w, "owner_republish")


def test_the_owner_event_survives_a_hold_and_republishes_with_no_session(world: World) -> None:
    """Nothing is kept in memory: a held dispatch (or a restart) republishes later."""
    w = world
    job, tid, item = _failed(w)
    real = w.runner.dispatch
    w.runner.dispatch = lambda j: None  # type: ignore[method-assign]
    assert _post(w, item["id"], tid).status_code == 200
    (ev,) = _events(w, "owner_republish")
    assert ev["head"] == _record(w, job, tid)["after"]["sha"] and ev["inbox_item_id"] == item["id"]
    assert w.store.get_task(tid).state == "failed" and not _events(w, "republish")
    assert not hasattr(w.runner, "_owner_pub")
    w.runner.dispatch = real  # type: ignore[method-assign]
    real(job)
    assert w.store.get_task(tid).state in ("pr_open", "reviewed")
    assert _w1_calls(w, job) == 1
    (rep,) = _events(w, "republish")
    assert rep["owner_event"] and rep["inbox_item_id"] == item["id"]


def test_a_failed_transition_leaves_no_event(world: World, monkeypatch: Any) -> None:
    from vigild.jobs import service
    from vigild.jobs.fsm import TransitionError

    w = world
    _job, tid, item = _failed(w)

    def boom(*a: Any, **k: Any) -> Any:
        raise TransitionError("no")

    monkeypatch.setattr(service, "transition", boom)
    assert _post(w, item["id"], tid).status_code == 409
    assert not _events(w, "owner_republish")
    assert w.runner._owner_event(tid) is None
    assert w.store.get_inbox_item(item["id"]).status == "open"


def test_an_owner_republish_followed_by_a_failure_is_not_reused(world: World) -> None:
    """If the owner's publish dies on a vigild error (no `republish` event), the task's
    later failure ends the owner's request: a retry starts a session, never the old head."""
    w = world
    job, tid, item = _failed(w)
    w.store.add_event(
        "owner_republish", {"task": tid, "head": "0" * 40, "inbox_item_id": item["id"]},
        "human", job_id=job, task_id=tid,
    )  # fmt: skip
    w.store.add_event(
        "task_failed", {"title": f"{tid}: vigild error"}, "human", job_id=job, task_id=tid
    )
    assert w.runner._owner_event(tid) is None
    assert w.runner._republish_inputs(tid) is None  # a session, not a stale republish


def test_a_consumed_republish_is_not_used_again(world: World) -> None:
    w = world
    job, tid, item = _failed(w)
    assert _post(w, item["id"], tid).status_code == 200
    assert w.runner._owner_event(tid) is None  # consumed by its `republish` event
    w.store.update_task(tid, state="failed")
    w.store.add_event(
        "task_failed", {"title": f"{tid}: worker session failed"}, "human", job_id=job, task_id=tid
    )
    assert w.runner._republish_inputs(tid) is None  # an ordinary retry starts a session

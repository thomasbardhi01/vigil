"""#152: a retry after a publish refusal republishes the vault head; it starts no worker
session and books no reservation. A retry after a session failure still runs a session."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from typing import Any

import httpx2

from tests.jobs.test_coord_loop import (
    World,
    _approve,
    _events,
    _failure_item,
    _flaky,
    auth,
    world,  # noqa: F401
)
from vigild.github.publish import PublishError, RestPulls


def _w1_calls(w: World, job: str) -> int:
    return sum(1 for role, tid in w.standin.calls if role == "worker" and tid == f"{job}-w1")


def _refuse_w1_once(w: World) -> None:
    real = w.publisher.publish
    left = [1]

    def flaky(**kw: Any) -> str:
        if str(kw["branch"]).endswith("-w1") and left[0]:
            left[0] -= 1
            raise PublishError("422: Validation Failed (title is too long)")
        return real(**kw)

    w.publisher.publish = flaky  # type: ignore[method-assign]


def test_a_retry_after_a_publish_refusal_republishes_the_head_with_no_session(
    world: World,
) -> None:
    w = world
    _refuse_w1_once(w)
    job = _approve(w)
    tid = f"{job}-w1"
    assert w.store.get_task(tid).state == "failed"
    item = _failure_item(w, job)
    assert "publish refused" in json.dumps(item["body"]["tasks"])
    calls = _w1_calls(w, job)
    reservations = w.store.q("SELECT id FROM reservations WHERE task_id=?", (tid,))
    r = w.client.post(f"/api/inbox/{item['id']}/retry", headers=auth(w.tokens.admin))
    assert r.status_code == 200, r.text
    assert w.store.get_task(tid).state in ("pr_open", "reviewed")  # then the job reviews
    assert _w1_calls(w, job) == calls == 1  # no worker session started
    assert w.store.q("SELECT id FROM reservations WHERE task_id=?", (tid,)) == reservations
    assert w.store.get_job(job).state.value == "ready"
    (rep,) = [e for e in _events(w, "republish") if e["task_id"] == tid]
    (opened,) = [e for e in _events(w, "pr_open") if e["task_id"] == tid]
    assert rep["head"] == opened["head"] and rep["result"] == opened["pr_url"]
    assert f"vigil/{job}-w1" in [p["head"] for p in w.publisher.prs]


def test_a_second_refusal_fails_the_task_with_the_new_error(world: World) -> None:
    w = world
    real = w.publisher.publish

    def refuse(**kw: Any) -> str:
        if str(kw["branch"]).endswith("-w1"):
            raise PublishError("403: still no")
        return real(**kw)

    w.publisher.publish = refuse  # type: ignore[method-assign]
    job = _approve(w)
    item = _failure_item(w, job)
    w.client.post(f"/api/inbox/{item['id']}/retry", headers=auth(w.tokens.admin))
    tid = f"{job}-w1"
    assert w.store.get_task(tid).state == "failed"
    assert _w1_calls(w, job) == 1
    assert "403: still no" in json.dumps(_events(w, "task_failed")[-1])


def test_a_retry_after_a_session_failure_still_starts_a_session(world: World) -> None:
    w = world
    w.standin.worker_edit = _flaky({"w1"})
    job = _approve(w)
    item = _failure_item(w, job)
    r = w.client.post(f"/api/inbox/{item['id']}/retry", headers=auth(w.tokens.admin))
    assert r.status_code == 200, r.text
    assert _w1_calls(w, job) == 2
    assert not _events(w, "republish")


def test_a_422_keeps_githubs_reason() -> None:
    body = {
        "message": "Validation Failed",
        "errors": [{"resource": "PullRequest", "code": "custom", "message": "title is too long"}],
    }

    def handler(req: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(422, json=body)

    pulls = RestPulls(httpx2.Client(transport=httpx2.MockTransport(handler)), "ghs_x")
    try:
        pulls.create_pull("o/x", head="h", base="main", title="t", body="b", draft=True)
    except PublishError as e:
        assert "422: Validation Failed" in str(e) and "title is too long" in str(e)
    else:
        raise AssertionError("a 422 was accepted")

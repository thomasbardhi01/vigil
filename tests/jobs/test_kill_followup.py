"""#60, the follow-up to the kill (#52, #58):

1. Terminal states are final: the FSM refuses every move out of one, whoever asks,
   and logs the refusal.
2. A run that outlives the kill's wait marks its sessions `killed` (the `Halted` path
   too), opens no page or inbox item on the abandoned job, and books nothing.
3. A call that was authorized before the kill's revoke cannot hold after its drain
   (tests/gateway/test_kill_race.py)."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

import pytest

from tests.jobs.test_coord_loop import World, _request, auth, world  # noqa: F401
from tests.jobs.test_kill import (
    Hung,
    _events,
    _kill,
    _open_reservations,
    _spec_item,
)
from vigild.budget import BudgetExceeded
from vigild.jobs.fsm import TERMINAL, Actor, TransitionError, transition
from vigild.jobs.model import JobState, Role
from vigild.jobs.runner import LIVE_SESSION
from vigild.verifier import Halted

S = JobState


# --- 1. terminal states are final -----------------------------------------------------------

CHANNELS = [None, "inbox", "api", "cli", "somewhere"]
EVIDENCES = [{}, {"action": "kill"}, {"action": "abandon"}, {"action": "replan"},
             {"reason": "x"}]  # fmt: skip


@pytest.mark.parametrize("final", TERMINAL)
@pytest.mark.parametrize("target", list(S))
@pytest.mark.parametrize("actor", list(Actor))
def test_nothing_leaves_a_terminal_state(
    world: World, caplog: pytest.LogCaptureFixture, final: S, target: S, actor: Actor
) -> None:
    w = world
    job = _request(w)
    w.store._write_state(job, final, None)
    for channel in CHANNELS:
        for evidence in EVIDENCES:
            for force in (False, True):
                before = len(_events(w, job, "transition_refused"))
                with (
                    caplog.at_level(logging.WARNING, logger="vigild.jobs.fsm"),
                    pytest.raises(TransitionError, match="no transition out of it"),
                ):
                    transition(
                        w.store, job, target, actor, channel=channel, evidence=evidence,
                        force=force,
                    )  # fmt: skip
                assert w.store.get_job(job).state is final
                refused = _events(w, job, "transition_refused")
                assert len(refused) == before + 1, "every refusal is logged as an event"
                assert refused[-1].data["from"] == final.value
                assert refused[-1].data["to"] == target.value
                assert refused[-1].data["actor"] == actor.value
    assert any(final.value in r.getMessage() for r in caplog.records), "and in the log"
    assert not _events(w, job, "state") or all(
        e.data["to"] != target.value
        for e in _events(w, job, "state")
        if e.data["from"] == final.value
    )


def test_the_already_replies_stay_200(world: World) -> None:
    w = world
    for final in (S.DONE, S.ABANDONED):
        job = _request(w)
        w.store._write_state(job, final, None)
        if final is S.ABANDONED:
            w.store.add_event("job_killed", {}, "human", job_id=job)
        r = _kill(w, job)
        assert r.status_code == 200 and r.json()["already"] == final.value
        assert w.store.get_job(job).state is final


# --- 2. a run that outlives the kill's wait -------------------------------------------------


@dataclass
class Stubborn(Hung):
    """A worker that ignores the stop until `release` is called: its run outlives the
    kill's wait, as a container that takes a while to die does."""

    def stop_job(self, job_id: str, session_ids: list[str]) -> int:
        self.stop_calls.append((job_id, list(session_ids)))
        return len(session_ids)

    def release(self) -> None:
        self.stopped.set()


def _stubborn_midrun(w: World) -> tuple[str, Stubborn, threading.Thread]:
    hung = Stubborn(w.standin)
    w.runner.executor = hung
    job = _request(w)
    item = _spec_item(w)
    t = threading.Thread(
        target=lambda: w.client.post(
            f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={}
        ),
        daemon=True,
    )
    t.start()
    assert hung.ready.wait(20), "both workers should be running"
    return job, hung, t


def _running(w: World, job: str) -> list[str]:
    return [s.id for s in w.store.list_sessions(job) if s.status in LIVE_SESSION]


def test_a_run_that_outlives_the_wait_leaves_nothing_running_open_or_paged(world: World) -> None:
    w = world
    job, hung, t = _stubborn_midrun(w)
    booked: list[Any] = []
    real = w.budget.reserve

    def spy(**kw: Any) -> int:
        booked.append(kw)
        return real(**kw)

    r = w.runner.jobs.kill(job, Actor.OWNER, "api", wait=0.3)  # type: ignore[union-attr]
    assert r["killed"] is True and r["run_ended"] is False, "the run outlives the wait"
    w.budget.reserve = spy  # type: ignore[method-assign]
    hung.release()
    t.join(30)
    assert not t.is_alive()
    for _ in range(200):
        if not w.runner.busy(job):
            break
        threading.Event().wait(0.05)
    assert not w.runner.busy(job)
    assert _running(w, job) == [], "no session row is left running"
    assert {s.status for s in w.store.list_sessions(job) if s.role is Role.WORKER} == {"killed"}
    assert not [q for q in w.store.list_inbox() if q.job_id == job], "no page, no item"
    assert not _events(w, job, "page")
    assert booked == [], "nothing is reserved after the kill"
    assert _open_reservations(w) == []
    assert w.store.get_job(job).state is S.ABANDONED


def test_the_halted_path_marks_its_session_killed(world: World) -> None:
    w = world
    real = w.runner.verifier.verify
    seen: list[str] = []

    def verify(**kw: Any) -> Any:
        if not seen:  # the first worker's verifier: the kill lands, then it halts
            seen.append(kw["task_id"])
            w.runner.jobs.kill(  # type: ignore[union-attr]
                w.store.get_task(kw["task_id"]).job_id, Actor.OWNER, "api", wait=0.2
            )
            raise Halted()
        return real(**kw)

    w.runner.verifier.verify = verify  # type: ignore[method-assign]
    job = _request(w)
    item = _spec_item(w)
    w.client.post(f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={})
    assert seen
    assert w.store.get_job(job).state is S.ABANDONED
    assert _running(w, job) == []
    assert not [q for q in w.store.list_inbox() if q.job_id == job]
    assert _open_reservations(w) == []


def test_fail_on_a_killed_job_still_closes_the_session(world: World) -> None:
    w = world
    job, hung, t = _stubborn_midrun(w)
    s = next(s for s in w.store.list_sessions(job) if s.role is Role.WORKER)
    tid = s.task_id
    assert tid
    w.runner.jobs.kill(job, Actor.OWNER, "api", wait=0.2)  # type: ignore[union-attr]
    assert w.runner._fail(job, s, tid, "late", {"why": "x"}) is False
    assert w.store.get_session(s.id).status == "killed"
    assert w.store.get_task(tid).state == "abandoned", "the task is not reset"
    assert not _events(w, job, "task_failed")
    hung.release()
    t.join(30)


# --- every page and item path checks the kill first -----------------------------------------


def _killed_job(w: World) -> str:
    job = _request(w)
    w.store._write_state(job, S.BUILDING, None)
    assert _kill(w, job).json()["state"] == "abandoned"
    return job


def test_no_page_or_item_is_opened_on_an_abandoned_job(world: World) -> None:
    w = world
    job = _killed_job(w)
    before = len(w.store.list_inbox())
    w.runner._page(job, "late", {"kind": "x"})
    w.runner.jobs.page(job, "late", {"kind": "x"})  # type: ignore[union-attr]
    w.runner._breaker_page(job, "late", {"kind": "x"})
    w.store.create_inbox_item("questions", "page", job, "late", {})
    w.store.create_inbox_item("ready", "ready_to_merge", job, "late", {})
    assert len(w.store.list_inbox()) == before
    assert not [q for q in w.store.list_inbox("resolved") if q.job_id == job and q.title == "late"]
    assert not _events(w, job, "page")
    assert _events(w, job, "inbox_item_suppressed"), "the suppression is recorded"


def test_a_page_for_a_job_that_is_not_abandoned_is_still_opened(world: World) -> None:
    w = world
    job = _request(w)
    w.runner._page(job, "real", {"kind": "x"})
    assert [q for q in w.store.list_inbox() if q.job_id == job and q.title == "real"]


def test_the_unstripped_page_after_a_kill_is_not_opened(world: World) -> None:
    """The tail of a review pass: the kill lands after the state check, `_unstripped`
    reports a task whose publish was skipped, and the pass would block and page."""
    w = world
    job = _request(w)
    w.store._write_state(job, S.IN_REVIEW, None)
    tid = w.store.list_tasks(job)[0].id if w.store.list_tasks(job) else "t-1"

    def unstripped(j: Any) -> tuple[dict[str, str], set[str]]:
        _kill(w, job)
        return {tid: "its PR could not be brought up to date without .vigil/: killed"}, set()

    w.runner._unstripped = unstripped  # type: ignore[method-assign]
    w.runner._review_task = lambda j, t: ("clean", "ok")  # type: ignore[method-assign]
    tasks = w.store.list_tasks(job) or []
    w.runner._review_pass(job, w.store.get_job(job), tasks, more=False)
    assert w.store.get_job(job).state is S.ABANDONED
    assert not [q for q in w.store.list_inbox() if q.job_id == job]


def test_no_reservation_is_opened_for_an_abandoned_job(world: World) -> None:
    w = world
    job = _killed_job(w)
    with pytest.raises(BudgetExceeded) as e:
        w.budget.reserve(
            session_id=None, task_id=None, amount=0.5, purpose="review_stage", job_id=job
        )
    assert e.value.cap == "abandoned"
    s = w.store.create_session(job, Role.REVIEWER, backend_preset="claude-sonnet")
    with pytest.raises(BudgetExceeded):
        w.budget.reserve(session_id=s.id, task_id=None, amount=0.4, purpose="reviewer")
    with pytest.raises(BudgetExceeded):
        w.budget.draw(1, session_id=s.id, amount=0.4, purpose="reviewer")
    assert _open_reservations(w) == []

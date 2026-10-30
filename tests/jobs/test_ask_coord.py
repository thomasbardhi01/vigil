"""A worker's question is a wait for the owner, not a failure (#71).

The page reads "<task> is waiting on you" with the whole question; `POST
/api/inbox/{id}/resume` takes an optional note that answers it (an `owner_answer` event,
fenced into the re-run worker's packet); a wave of only questions does not count toward
the repo_failures breaker, while a real failure beside a question still does."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from typing import Any

from tests.jobs.test_coord_loop import (  # noqa: F401
    World,
    _approve,
    _work,
    auth,
    world,
)
from vigild.executors.runtime import ExecOutcome, SessionSpec
from vigild.jobs.model import Role

QUESTION = "Which env var name should the limiter read? " + "x" * 5000


def _ask_on_w2(w: World, question: str = "Which env var name?", times: int = 1) -> list[str]:
    """w2 asks `times` times, then works; w1 always works. Returns the worker packets."""
    packets: list[str] = []
    asked = [0]

    def edit(spec: SessionSpec, task: dict[str, Any]) -> None:
        d = spec.clone / ".vigil" / spec.job_id / str(spec.task_id)
        d.mkdir(parents=True, exist_ok=True)
        if str(spec.task_id).endswith("w2") and asked[0] < times:
            asked[0] += 1
            (d / "ask_coord.json").write_text(json.dumps({"question": question}))
        else:
            _work(spec.clone, task["spec"]["files_in_scope"][0])

    w.standin.worker_edit = edit
    w.standin.on_session = lambda spec: (
        packets.append(spec.packet) if spec.role is Role.WORKER else None
    )
    return packets


def _items(w: World) -> list[dict[str, Any]]:
    out = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
    return list(out)


def _failures(w: World) -> int:
    rows = w.store.q("SELECT count FROM breakers WHERE kind='repo_failures'")
    return int(rows[0]["count"]) if rows else 0


def test_ask_coord_page_title_says_waiting_on_you(world: World) -> None:
    w = world
    _ask_on_w2(w)
    job = _approve(w)
    ask = next(q for q in _items(w) if q["kind"] == "ask_coord")
    assert ask["title"] == f"{job}-w2 is waiting on you"
    assert ask["body"]["resumable"] is True and "resume" in ask["body"]["actions"]
    page = next(q for q in _items(w) if q["kind"] == "page")
    assert f"{job}-w2 is waiting on you" in page["title"]
    assert "asks its coord" not in page["title"]


def test_ask_coord_full_question_is_on_the_page(world: World) -> None:
    w = world
    _ask_on_w2(w, QUESTION)
    job = _approve(w)
    ask = next(q for q in _items(w) if q["kind"] == "ask_coord")
    assert ask["body"]["question"].startswith("Which env var name should the limiter read?")
    assert len(ask["body"]["question"]) > 4000  # the whole question, not a cut
    page = next(q for q in _items(w) if q["kind"] == "page")
    assert page["body"]["tasks"][f"{job}-w2"]["question"] == ask["body"]["question"]


def test_ask_coord_resume_with_note_answers_the_worker(world: World) -> None:
    w = world
    packets = _ask_on_w2(w)
    job = _approve(w)
    ask = next(q for q in _items(w) if q["kind"] == "ask_coord")
    packets.clear()
    r = w.client.post(
        f"/api/inbox/{ask['id']}/resume",
        json={"note": "Use LIMIT_PER_MIN."},
        headers=auth(w.tokens.admin),
    )
    assert r.status_code == 200, r.text
    (ev,) = [e for e in w.store.events(job_id=job) if e.type == "owner_answer"]
    assert ev.task_id == f"{job}-w2" and ev.data["note"] == "Use LIMIT_PER_MIN."
    assert [p for p in packets if "LIMIT_PER_MIN" in p], "the answer is in a re-run packet"
    assert all("LIMIT_PER_MIN" not in p for p in packets if f"{job}-w1" in p.split("```")[1])
    # the answer is fenced, as untrusted text
    assert "<<<UNTRUSTED owner-answer " in next(p for p in packets if "LIMIT_PER_MIN" in p)
    # a note with nothing to answer, or no text, is refused
    bad = w.client.post(
        f"/api/inbox/{ask['id']}/resume", json={"note": 5}, headers=auth(w.tokens.admin)
    )
    assert bad.status_code == 422
    assert [q for q in _items(w) if q["id"] == ask["id"]] == []  # resolved by the resume


def test_ask_coord_question_not_repo_failure(world: World) -> None:
    w = world
    _ask_on_w2(w)
    job = _approve(w)
    assert w.store.get_job(job).state.value == "blocked"
    assert _failures(w) == 0


def test_ask_coord_other_failures_still_count(world: World) -> None:
    w = world
    _ask_on_w2(w)
    real = w.standin.run

    def run(spec: SessionSpec, token: str, sink: Any) -> ExecOutcome:
        if spec.role is Role.WORKER and str(spec.task_id).endswith("w1"):
            return ExecOutcome("timeout", None, {}, "over 40 min")
        return real(spec, token, sink)

    w.standin.run = run  # type: ignore[method-assign]
    _approve(w)
    assert _failures(w) == 1

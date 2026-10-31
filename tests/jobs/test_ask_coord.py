"""A worker's question is a wait for the owner (issue #71): its page says so and keeps the
whole question, it is not a repo failure, and an answer given on resume reaches the
re-run worker's packet, labelled by who gave it."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from tests.api.test_coord_token import HEADING, RULING
from tests.jobs.test_coord_loop import (  # noqa: F401
    REPO,
    World,
    _approve,
    _failure_item,
    _work,
    auth,
    world,
)
from vigild.breakers import Kind
from vigild.executors.base import SessionSpec
from vigild.jobs.rulings import label_note

Edit = Callable[[SessionSpec, dict[str, Any]], None]


def _ask(question: str, *, only: str | None = None) -> Edit:
    """Workers that ask (all, or the one whose task id ends `only`); the rest work."""
    state = {"asking": True}

    def edit(spec: SessionSpec, task: dict[str, Any]) -> None:
        if state["asking"] and (only is None or str(spec.task_id).endswith(only)):
            d = spec.clone / ".vigil" / spec.job_id / str(spec.task_id)
            d.mkdir(parents=True, exist_ok=True)
            (d / "ask_coord.json").write_text(json.dumps({"question": question}))
        else:
            _work(spec.clone, task["spec"]["files_in_scope"][0])

    edit.state = state  # type: ignore[attr-defined]
    return edit


def _failures(w: World) -> int:
    b = w.runner.breakers._row(Kind.REPO_FAILURES, f"repo:{REPO}")
    return b.count if b else 0


def _page(w: World, job: str) -> dict[str, Any]:
    return _failure_item(w, job, kind="ask_coord")


def _events(w: World, job: str, kind: str) -> list[Any]:
    return [e for e in w.store.events(job_id=job) if e.type == kind]


def test_ask_coord_page_title(world: World) -> None:
    w = world
    w.standin.worker_edit = _ask("which?", only="w1")
    job = _approve(w)
    assert w.store.get_job(job).state.value == "blocked"
    page = _page(w, job)
    assert page["title"] == f"{job}-w1 is waiting on you"
    assert "failed" not in page["title"]
    assert not [
        q
        for q in w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
        if q["body"].get("kind") == "worker_failed"
    ]


def test_ask_coord_full_question(world: World) -> None:
    w = world
    question = "Q" * 5000 + "é\n" + "z" * 5000
    w.standin.worker_edit = _ask(question, only="w1")
    job = _approve(w)
    page = _page(w, job)
    assert page["body"]["tasks"][f"{job}-w1"]["question"] == question
    items = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["questions"]
    (asked,) = [q for q in items if q["kind"] == "ask_coord"]
    assert asked["body"]["question"] == question
    assert asked["title"] == f"{job}-w1 is waiting on you"


def test_ask_coord_resume_with_note(world: World) -> None:
    w = world
    edit = _ask("which?")
    w.standin.worker_edit = edit
    job = _approve(w)
    page = _page(w, job)
    url = f"/api/inbox/{page['id']}/resume"
    big = w.client.post(url, headers=auth(w.tokens.admin), json={"note": "x" * 9000})
    assert big.status_code == 413
    assert w.client.post(url, headers=auth(w.tokens.admin), json={"note": "  "}).status_code == 422
    assert w.store.get_job(job).state.value == "blocked"
    edit.state["asking"] = False  # type: ignore[attr-defined]
    r = w.client.post(url, headers=auth(w.tokens.admin), json={"note": "use option B"})
    assert r.status_code == 200, r.text
    answers = _events(w, job, "owner_answer")
    assert {e.task_id for e in answers} == {f"{job}-w1", f"{job}-w2"}
    assert answers[0].data["answer"] == "use option B" and answers[0].provenance == "human"
    last = [p for role, p in w.standin.packets if role == "worker"][-1]
    assert "use option B" in last and "owner answer" in last and "which?" in last


def test_ask_coord_question_not_repo_failure(world: World) -> None:
    w = world
    w.runner.breakers.failure(Kind.REPO_FAILURES, f"repo:{REPO}", 99, {"job": "earlier"})
    assert _failures(w) == 1
    w.standin.worker_edit = _ask("which?")
    job = _approve(w)
    assert w.store.get_job(job).state.value == "blocked"
    assert _failures(w) == 1


def test_ask_coord_other_failures_still_count(world: World) -> None:
    w = world
    ask = _ask("which?", only="w1")

    def edit(spec: SessionSpec, task: dict[str, Any]) -> None:
        ask(spec, task)
        if str(spec.task_id).endswith("w2"):
            (spec.clone / "README.md").write_text("out of scope\n")

    w.standin.worker_edit = edit
    before = _failures(w)
    job = _approve(w)
    assert w.store.get_job(job).state.value == "blocked"
    assert _failures(w) == before + 1
    item = _failure_item(w, job)  # a mixed wave is a failure page, with its actions
    assert "replan" in item["body"]["actions"]


def _answered(w: World, token: str, body: dict[str, Any]) -> tuple[str, str]:
    edit = _ask("which?", only="w1")
    w.standin.worker_edit = edit
    job = _approve(w)
    edit.state["asking"] = False  # type: ignore[attr-defined]
    r = w.client.post(f"/api/inbox/{_page(w, job)['id']}/resume", headers=auth(token), json=body)
    assert r.status_code == 200, r.text
    packet = [p for role, p in w.standin.packets if role == "worker"][-1]
    return job, packet


def test_ask_coord_answer_attribution_owner(world: World) -> None:
    w = world
    job, packet = _answered(w, w.tokens.admin, {"note": "use B", "ruling": RULING})
    assert [e.type for e in w.store.events(job_id=job) if "answer" in e.type] == ["owner_answer"]
    assert "owner answer" in packet and "use B" in packet and "coord answer" not in packet


def test_ask_coord_answer_attribution_coord(world: World) -> None:
    w = world
    job, packet = _answered(w, w.tokens.coord, {"note": "use B", "ruling": RULING})
    assert [e.type for e in w.store.events(job_id=job) if "answer" in e.type] == ["coord_answer"]
    assert f"coord answer (ruling: {HEADING})" in packet
    assert label_note("use B", HEADING) in packet
    assert "owner answer" not in packet


def test_ask_coord_coord_note_needs_a_ruling(world: World) -> None:
    w = world
    w.standin.worker_edit = _ask("which?", only="w1")
    job = _approve(w)
    r = w.client.post(
        f"/api/inbox/{_page(w, job)['id']}/resume",
        headers=auth(w.tokens.coord),
        json={"note": "use B"},
    )
    assert r.status_code == 422
    assert not _events(w, job, "coord_answer")

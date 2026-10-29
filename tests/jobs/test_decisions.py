"""A per-job decisions log (ADR-0005 part 4): one `decisions.jsonl` vault artifact, append
only. The coord writes `.vigil/<job>/decisions.jsonl` in its clone and vigild reads it as a
vault blob; vigild appends its own lines (gate refusal, replan, escalation); workers never
write it. Every later session but the auditor's gets it, fenced, in its packet."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.jobs.test_coord_loop import (  # noqa: F401
    SPEC,
    World,
    _approve,
    _events,
    _failure_item,
    _flaky,
    _request,
    plan,
    world,
)
from tests.jobs.test_replan_note import _replan
from tests.review.test_review_stage import CHANGES, CLEAN_REVIEW
from vigild.contract.models import DecisionLine
from vigild.executors.base import SessionSpec
from vigild.jobs import decisions
from vigild.jobs.model import Role
from vigild.packets.fence import FENCE_RE
from vigild.provenance import Provenance

NAME = "decisions.jsonl"
SECRET = "sk-" + "abcdefgh12345678"  # shaped like a key; the redact tests use the same shape


def _line(text: str, **kw: Any) -> str:
    return json.dumps(
        {"ts": "2026-10-28T10:00:00Z", "by": "coord", "kind": "scope", "text": text} | kw
    )


def _coord_writes(w: World, *lines: str) -> None:
    def extra(clone: Path, j: str) -> None:
        (clone / ".vigil" / j / NAME).write_text("\n".join(lines) + "\n")

    w.standin.coord_extra = extra


def _stored(w: World, job: str) -> list[dict[str, Any]]:
    art = w.store.get_artifact(job, NAME)
    assert art is not None
    return [json.loads(x) for x in art.content.splitlines()]


def _fenced(packet: str) -> list[str]:
    return [m.group(3) for m in FENCE_RE.finditer(packet) if m.group(1) == "decisions"]


def test_the_model_caps_text_at_300_characters() -> None:
    DecisionLine(ts="t", by="coord", kind="scope", text="x" * 300)
    with pytest.raises(ValueError):
        DecisionLine(ts="t", by="coord", kind="scope", text="x" * 301)
    with pytest.raises(ValueError):
        DecisionLine(ts="t", by="human", kind="scope", text="x")  # type: ignore[arg-type]


def test_coord_lines_are_stored_as_coord_and_an_invalid_one_is_dropped(world: World) -> None:
    w = world
    _coord_writes(
        w,
        _line("cut the CLI from scope"),
        _line("x" * 301),  # too long: dropped
        _line("rejected a new table", by="vigild", kind="approach"),  # stored as coord
    )
    job = _request(w)
    got = _stored(w, job)
    assert [(x["by"], x["text"]) for x in got] == [
        ("coord", "cut the CLI from scope"),
        ("coord", "rejected a new table"),
    ]
    (ev,) = [e for e in _events(w, "decisions") if e["dropped"]]
    assert ev["kept"] == 2 and ev["dropped"] == 1


def test_a_secret_in_a_line_is_redacted(world: World) -> None:
    w = world
    _coord_writes(w, _line(f"key was {SECRET} in the issue"))
    job = _request(w)
    raw = w.store.get_artifact(job, NAME).content  # type: ignore[union-attr]
    assert SECRET not in raw and "[redacted]" in raw


def test_a_gate_refusal_then_a_replan_append_and_keep_the_earlier_lines(world: World) -> None:
    w = world
    w.standin.worker_edit = _flaky({"w1"})
    bad = SPEC.replace(" test: `pytest -q tests/test_runbook.py`", "")
    w.standin.coord_drafts = [lambda j: (bad, plan(j))]
    _coord_writes(w, _line("first line"))
    job = _approve(w)
    after_gate = w.store.get_artifact(job, NAME).content  # type: ignore[union-attr]
    kinds = [x["kind"] for x in _stored(w, job)]
    assert "gate" in kinds and kinds.count("scope") >= 1
    gate = next(x for x in _stored(w, job) if x["kind"] == "gate")
    assert gate["by"] == "vigild"
    item = _failure_item(w, job)
    assert _replan(w, item, "Narrow it.\nSecond line.").status_code == 200
    final = w.store.get_artifact(job, NAME).content  # type: ignore[union-attr]
    assert final.startswith(after_gate)  # the old lines, unchanged
    replan = [x for x in _stored(w, job) if x["kind"] == "replan"]
    assert replan and replan[0]["by"] == "vigild" and replan[0]["text"] == "Narrow it."


def test_a_replan_without_a_note_says_so(world: World) -> None:
    w = world
    w.standin.worker_edit = _flaky({"w1"})
    job = _approve(w)
    r = w.client.post(
        f"/api/inbox/{_failure_item(w, job)['id']}/replan",
        headers={"Authorization": f"Bearer {w.tokens.admin}"},
    )
    assert r.status_code == 200, r.text
    assert [x["text"] for x in _stored(w, job) if x["kind"] == "replan"] == ["no note"]


def test_every_later_session_but_the_auditor_gets_the_fenced_log(world: World) -> None:
    w = world
    _coord_writes(w, _line("MARK-DECISION"))
    w.standin.worker_edit = _flaky({"w1"})
    seen = {"n": 0}

    def review(spec: SessionSpec) -> Any:
        seen["n"] += 1
        return CHANGES if seen["n"] == 1 else CLEAN_REVIEW

    w.standin.review = review
    job = _approve(w)
    item = _failure_item(w, job)
    assert _replan(w, item, "again").status_code == 200
    by_role: dict[str, list[SessionSpec]] = {}
    for s in w.standin.specs:
        by_role.setdefault(s.role.value, []).append(s)
    assert len(by_role[Role.COORD.value]) >= 2
    # the replan coord, then every worker session (the first, the retry, a fix round), the reviewer
    for s in by_role[Role.COORD.value][1:] + by_role[Role.WORKER.value][1:]:
        assert "MARK-DECISION" in "".join(_fenced(s.packet)), s.role
    assert len(by_role[Role.WORKER.value]) >= 2


def test_the_fix_round_the_reviewer_and_not_the_auditor_get_the_log(world: World) -> None:
    w = world
    _coord_writes(w, _line("MARK-DECISION"))
    seen = {"n": 0}

    def review(spec: SessionSpec) -> Any:
        seen["n"] += 1
        return CHANGES if seen["n"] == 1 else CLEAN_REVIEW

    w.standin.review = review
    _approve(w)
    workers = [s for s in w.standin.specs if s.role is Role.WORKER]
    assert len(workers) >= 2  # the build, then the fix round
    for s in workers:
        assert "MARK-DECISION" in "".join(_fenced(s.packet))
    reviewers = [s for s in w.standin.specs if s.role is Role.REVIEWER]
    assert len(reviewers) >= 2
    for s in reviewers:
        assert "MARK-DECISION" in "".join(_fenced(s.packet))
    auditors = [s for s in w.standin.specs if s.role is Role.AUDITOR]
    assert auditors
    for s in auditors:
        assert "decisions" not in s.packet and "MARK-DECISION" not in s.packet


def test_a_workers_own_log_is_not_appended(world: World) -> None:
    w = world
    _coord_writes(w, _line("coord line"))

    def sneaky(spec: SessionSpec, task: dict[str, Any]) -> None:
        from tests.jobs.test_coord_loop import _work

        _work(spec.clone, task["spec"]["files_in_scope"][0])
        d = spec.clone / ".vigil" / spec.job_id
        d.mkdir(parents=True, exist_ok=True)
        (d / NAME).write_text(_line("WORKER-WROTE-THIS") + "\n")

    w.standin.worker_edit = sneaky
    job = _approve(w)
    assert "WORKER-WROTE-THIS" not in w.store.get_artifact(job, NAME).content  # type: ignore[union-attr]
    assert [x["text"] for x in _stored(w, job)] == ["coord line"]


def test_a_log_over_4000_characters_keeps_the_newest_lines_and_notes_the_drop(world: World) -> None:
    w = world
    job = _request(w)
    for i in range(40):
        decisions.add(w.store, job, "vigild", "gate", f"line-{i:02d} " + "y" * 250)
    packet = decisions.section(w.store, job)["decisions"]
    assert len(packet) <= 4000 + 200  # the cap, plus the one-line note
    assert "line-39" in packet and "line-00" not in packet
    assert "older line" in packet and "dropped" in packet
    assert packet.index("line-38") < packet.index("line-39")  # newest last
    assert w.store.get_artifact(job, NAME).provenance in {  # type: ignore[union-attr]
        Provenance.CLAUDE.value,
        Provenance.HUMAN.value,
    }

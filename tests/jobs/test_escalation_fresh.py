"""Escalation starts fresh too (#101, owner, 2026-10-28).

Rule 5 and attempt >= routing.escalate_attempt build the same fresh packet as a
fix round, plus every review round's findings; nothing is forked. The fork is only
for resuming a crashed session (tests/jobs/test_resume.py)."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

from typing import Any

from tests.conftest import auth
from tests.jobs.test_coord_loop import World, _approve, _failure_item, world  # noqa: F401
from tests.review.test_review_stage import CLEAN_REVIEW, MEDIUM, _rounds, _workers
from vigild.jobs.model import Role
from vigild.packets.assemble import FRESH_FINDINGS_CHARS, round_findings

FIRST_CALL_TOKENS = 20_000
R1 = {**CLEAN_REVIEW, "verdict": "changes", "findings": [{**MEDIUM, "claim": "ROUND-ONE-CLAIM"}]}
R2 = {**CLEAN_REVIEW, "verdict": "changes", "findings": [{**MEDIUM, "claim": "ROUND-TWO-CLAIM"}]}


def _escalated(w: World) -> tuple[str, list[Any]]:
    w.standin.review = _rounds({"w1": [R1, R2]})
    job = _approve(w)
    assert w.store.get_task(f"{job}-w1").tier_reason.startswith("rule5")  # type: ignore[union-attr]
    return job, _workers(w, "w1")


def test_an_escalated_worker_forks_nothing_and_sees_every_round(world: World) -> None:
    w = world
    job, (*_, esc) = _escalated(w)
    assert esc.resume is None
    assert not w.store.q("SELECT 1 FROM events WHERE job_id=? AND type='fork'", (job,))
    assert len(esc.packet) / 4 < FIRST_CALL_TOKENS
    p = esc.packet
    assert "ROUND-ONE-CLAIM" in p and "ROUND-TWO-CLAIM" in p  # every round, round by round
    assert p.index("ROUND-ONE-CLAIM") < p.index("ROUND-TWO-CLAIM")
    assert "The approved spec.md" in p and "<<<UNTRUSTED pr-diff" in p
    assert "<<<UNTRUSTED plan-md" in p and "<<<UNTRUSTED verifier-summary" in p
    assert "<<<UNTRUSTED review-history" in p  # fenced
    assert "## docs/feature-map.md (excerpt)" not in p  # no context pack


def test_a_worker_at_the_escalation_attempt_forks_nothing(world: World) -> None:
    w = world
    w.runner.cfg.routing.escalate_attempt = 1  # attempt 1 is already the escalation
    w.standin.review = _rounds({"w1": [R1]})
    job = _approve(w)
    workers = _workers(w, "w1")
    assert len(workers) >= 2
    assert all(s.resume is None for s in workers)
    assert not w.store.q("SELECT 1 FROM events WHERE job_id=? AND type='fork'", (job,))
    assert "ROUND-ONE-CLAIM" in workers[-1].packet
    assert len(workers[-1].packet) / 4 < FIRST_CALL_TOKENS


def test_an_s_task_escalation_builds_a_small_fresh_packet(world: World) -> None:
    """vi-0004's shape: the forked transcript did not fit the $0.60 cap's remainder."""
    w = world
    job, (_, second, esc) = _escalated(w)
    t = w.store.get_task(f"{job}-w1")
    assert t.contract["review_rounds"] == 2
    assert esc.resume is None and esc.session_id != second.session_id
    assert len(esc.packet) / 4 < FIRST_CALL_TOKENS


def _round(n: int, size: int) -> dict[str, Any]:
    return {
        "round": n,
        "findings": [
            {"severity": "high" if n % 2 else "medium", "file": "a.py", "line": n,
             "claim": f"CLAIM-{n} " + "x" * size, "fix": "y"}
        ],
    }  # fmt: skip


def test_older_rounds_are_listed_when_all_do_not_fit() -> None:
    rounds = [_round(n, 6000) for n in range(1, 7)]
    text = round_findings(rounds)
    assert len(text) <= FRESH_FINDINGS_CHARS + 2000
    assert "CLAIM-6 " in text and "CLAIM-5 " in text  # the newest in full
    assert "CLAIM-1 " not in text  # the oldest is dropped ...
    assert "round 1" in text and "high" in text and "dropped" in text  # ... but listed
    assert text.index("round 1") < text.index("CLAIM-6 ")


def test_all_rounds_in_full_when_they_fit() -> None:
    text = round_findings([_round(1, 10), _round(2, 10)])
    assert "CLAIM-1 " in text and "CLAIM-2 " in text and "dropped" not in text


def test_a_replan_after_review_rounds_sees_every_round(world: World) -> None:
    """The vi-0003 shape: a `review_rounds` page, then the owner's replan."""
    w = world
    r3 = {**CLEAN_REVIEW, "verdict": "changes", "findings": [{**MEDIUM, "claim": "ROUND-3-MARK"}]}
    w.standin.review = _rounds({"w1": [R1, R2, r3]})
    job = _approve(w)
    item = _failure_item(w, job, "review_rounds")
    r = w.client.post(f"/api/inbox/{item['id']}/replan", headers=auth(w.tokens.admin))
    assert r.status_code == 200, r.text
    second = [s for s in w.standin.specs if s.role is Role.COORD][-1]
    assert second.resume is None
    assert not w.store.q("SELECT 1 FROM events WHERE job_id=? AND type='fork'", (job,))
    p = second.packet
    assert "ROUND-ONE-CLAIM" in p and "ROUND-TWO-CLAIM" in p and "ROUND-3-MARK" in p
    assert "<<<UNTRUSTED review-history" in p and f"{job}-w1" in p
    assert len(p) / 4 < FIRST_CALL_TOKENS


def test_the_newest_round_is_bounded_too() -> None:
    big = _round(1, FRESH_FINDINGS_CHARS * 2)
    text = round_findings([big])
    assert len(text) <= FRESH_FINDINGS_CHARS + 200
    assert "(truncated)" in text

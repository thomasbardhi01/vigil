"""The runner pre-fills the coord's packet and clone (ADR-0005 part 5)."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

from tests.jobs.test_coord_loop import (  # noqa: F401
    REPO,
    World,
    _approve,
    _failure_item,
    _flaky,
    auth,
    world,
)
from tests.jobs.test_replan_note import AMENDED, CHANGELOG, NOTE, _arm, _replan
from vigild.executors.base import SessionSpec
from vigild.jobs.model import Role
from vigild.packets.fence import FENCE_RE
from vigild.packets.prefill import TODO


def _submit(w: World) -> str:
    r = w.client.post(
        "/api/jobs",
        headers=auth(w.tokens.admin),
        json={
            "repo": REPO,
            "title": "Document the rate limit",
            "request": "Edit `docs/runbook.md`; `docs/ghost.md` too.",
            "notes": [],
            "why": "support asks weekly",
            "value": 3,
            "risk": 1,
        },
    )
    assert r.status_code == 202, r.text
    return str(r.json()["id"])


def _approve_it(w: World) -> str:
    job = _submit(w)
    item = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["specs"][0]
    w.client.post(f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={})
    return job


def test_the_first_packet_carries_the_prefill_and_the_clone_the_skeleton(world: World) -> None:
    w = world
    seen: dict[str, str] = {}

    def look(spec: SessionSpec) -> None:
        if spec.role is Role.COORD and "spec" not in seen:
            d = spec.clone / ".vigil" / spec.job_id
            seen["spec"] = (d / "spec.md").read_text()
            seen["plan"] = (d / "plan.md").read_text()

    w.standin.on_session = look
    _submit(w)
    packet = next(s.packet for s in w.standin.specs if s.role is Role.COORD)
    fenced = [m for m in FENCE_RE.finditer(packet) if m.group(1) == "prefill"]
    assert len(fenced) == 1
    assert "`docs/runbook.md`" in fenced[0].group(3) and "docs/ghost.md" in fenced[0].group(3)
    assert "`docs/ghost.md`" not in seen["spec"]
    assert "- `docs/runbook.md`" in seen["spec"] and TODO in seen["spec"]
    assert '"files_in_scope"' in seen["plan"] and "docs/runbook.md" in seen["plan"]


def test_the_lean_packet_carries_it_too(world: World) -> None:
    w = world
    w.runner.cfg.routing.coord_packet = "lean"
    _submit(w)
    packet = next(s.packet for s in w.standin.specs if s.role is Role.COORD)
    assert "<<<UNTRUSTED prefill " in packet


def test_a_fresh_replan_carries_it_without_a_skeleton(world: World) -> None:
    w = world
    w.standin.worker_edit = _flaky({"w1"})
    job = _approve(w)
    item = _failure_item(w, job)
    _arm(w, AMENDED, CHANGELOG)
    assert _replan(w, item, NOTE).status_code == 200
    second = [s for s in w.standin.specs if s.role is Role.COORD][-1]
    assert "<<<UNTRUSTED prefill " in second.packet
    assert "The skeleton is in" not in second.packet  # the spec exists: no skeleton over it
    assert job

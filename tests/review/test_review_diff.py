"""#194: reviewers see the diff as it will be published. The executor commits `.vigil/` by
design and publish strips it, so a `.vigil/` path in a reviewer's diff is never a finding."""

from __future__ import annotations

import pytest

from tests.intake.test_spec_gate import MONEY, PLAN, SPEC
from tests.jobs.test_coord_loop import World, _approve
from tests.jobs.test_coord_loop import world as world
from vigild.intake.spec_gate import check_job_spec
from vigild.jobs.artifacts import parse_plan, parse_spec
from vigild.packets.assemble import PROMPTS_DIR, assemble_audit, assemble_review


def _inputs(w: World) -> tuple[str, object]:
    job_id = _approve(w)
    task_id = f"{job_id}-w1"
    job, t = w.store.get_job(job_id), w.store.get_task(task_id)
    head = w.runner._task_head(task_id)
    assert head
    base = w.runner.workspace.base_sha(task_id)
    # the vault does hold the artifacts: that is the premise
    assert ".vigil/" in w.runner.workspace.full_diff(job.repo, base, head)
    return task_id, w.runner._review_inputs(job, t, head, base, 1)


def test_the_review_packet_diff_has_the_real_file_and_no_vigil_path(world: World) -> None:
    _task, inputs = _inputs(world)
    assert "docs/feature-map.md" in inputs.diff  # type: ignore[attr-defined]
    assert ".vigil" not in inputs.diff  # type: ignore[attr-defined]
    p = assemble_review(
        inputs.rules,
        inputs.request,
        diff=inputs.diff,
        untrusted={},  # type: ignore[attr-defined]
    )
    assert "docs/feature-map.md" in p.parts["untrusted"]
    assert ".vigil/" not in p.parts["untrusted"]


def test_the_audit_packet_diff_is_the_same(world: World) -> None:
    _task, inputs = _inputs(world)
    p = assemble_audit(
        inputs.rules,
        inputs.request,
        diff=inputs.diff,
        review="[]",
        untrusted={},  # type: ignore[attr-defined]
    )
    assert "docs/feature-map.md" in p.parts["untrusted"]
    assert ".vigil/" not in p.parts["untrusted"]


def test_the_spec_gate_refuses_a_spec_that_forbids_vigil_files() -> None:
    bad = SPEC.replace(
        "AC1: the feature map lists the limit.",
        "AC1: the feature map lists the limit and no .vigil/ files are committed.",
    )
    errors = check_job_spec(parse_spec(bad), parse_plan(PLAN), MONEY)
    assert any(".vigil" in e and "vigild" in e for e in errors)
    bad_plan = PLAN.replace(
        '"done_when": "AC1 holds"', '"done_when": "AC1 holds; no .vigil/ files"'
    )
    errors = check_job_spec(parse_spec(SPEC), parse_plan(bad_plan), MONEY)
    assert any(".vigil" in e and "vigild" in e for e in errors)


def test_the_spec_gate_accepts_an_ordinary_spec() -> None:
    assert check_job_spec(parse_spec(SPEC), parse_plan(PLAN), MONEY) == []


@pytest.mark.parametrize("role", ["reviewer", "auditor"])
def test_prompts_say_vigil_paths_are_never_a_finding(role: str) -> None:
    text = (PROMPTS_DIR / f"{role}.md").read_text()
    assert ".vigil/" in text and len(text.splitlines()) <= 40

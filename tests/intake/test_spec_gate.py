"""The spec gate: per task (test_cmd + done_when) and per job (spec.md + plan.md)."""

from __future__ import annotations

from vigild.contract.models import Task
from vigild.intake.spec_gate import check_job_spec, check_task
from vigild.jobs.artifacts import parse_plan, parse_spec

MONEY = ["src/billing/**", "src/auth/**", "**/payments/**", "**/consent/**"]


def _task(**spec: object) -> Task:
    base: dict[str, object] = {
        "goal": "g",
        "test_cmd": "pytest -q",
        "done_when": "green",
        "files_in_scope": ["docs/a.md"],
    }
    base.update(spec)
    return Task.model_validate(
        {
            "task_id": "t1",
            "repo": "o/r",
            "base": "main",
            "why": "w",
            "value": 3,
            "risk": 1,
            "spec": base,
        }
    )


def test_task_with_test_and_done_passes() -> None:
    r = check_task(_task())
    assert r.ok and not r.needs_spec


def test_task_without_test_cmd_needs_a_spec() -> None:
    r = check_task(_task(test_cmd=None))
    assert not r.ok and r.needs_spec
    assert "test_cmd" in r.errors[0]


def test_task_without_done_when_needs_a_spec() -> None:
    r = check_task(_task(done_when="  "))
    assert not r.ok and r.needs_spec


SPEC = """<!-- provenance: claude -->
# Spec: docs for the rate limit

## Goal
Document the limit.

## Non-goals
- Changing the limit.

## Acceptance criteria
- AC1: the feature map lists the limit. test: `grep -q 'rate limit' docs/feature-map.md`
- AC2: the runbook says how to change it. test: `grep -q 'RATE_LIMIT' docs/runbook.md`

## Files in scope
- `docs/feature-map.md`
- `docs/runbook.md`

## Files out of scope
- `src/**`

## Money paths
none

## Risks
- Stale numbers.

## Interfaces
- None shared: each worker edits its own doc file.

## Rollback
Revert the PR.
"""

PLAN = """<!-- provenance: claude -->
# Plan

## Notes addressed
- "keep it short": adopted, one paragraph each.

## Workers
```json
{"workers": [
  {"task_id": "pa-0001-w1", "goal": "feature map row", "why": "AC1", "value": 3, "risk": 1,
   "size": "XS", "test_cmd": "grep -q 'rate limit' docs/feature-map.md",
   "done_when": "AC1 holds", "files_in_scope": ["docs/feature-map.md"], "must_fail_first": true},
  {"task_id": "pa-0001-w2", "goal": "runbook section", "why": "AC2", "value": 3, "risk": 1,
   "size": "XS", "test_cmd": "grep -q 'RATE_LIMIT' docs/runbook.md",
   "done_when": "AC2 holds", "files_in_scope": ["docs/runbook.md"], "must_fail_first": true}
],
 "verify": [
  {"criterion": "AC1", "level": 0, "why_not_higher": "a grep over a doc has no property to state"},
  {"criterion": "AC2", "level": 0, "why_not_higher": "same"}
]}
```
"""


def test_valid_spec_and_plan_pass() -> None:
    assert check_job_spec(parse_spec(SPEC), parse_plan(PLAN), MONEY) == []


def test_criterion_without_a_test_command_fails() -> None:
    spec = SPEC.replace(" test: `grep -q 'RATE_LIMIT' docs/runbook.md`", "")
    errors = check_job_spec(parse_spec(spec), parse_plan(PLAN), MONEY)
    assert any("AC2" in e and "test" in e for e in errors)


def test_missing_section_fails() -> None:
    spec = SPEC.replace("## Rollback\nRevert the PR.\n", "")
    errors = check_job_spec(parse_spec(spec), parse_plan(PLAN), MONEY)
    assert any("Rollback" in e for e in errors)


def test_invalid_worker_contract_fails() -> None:
    plan = PLAN.replace(
        '"value": 3, "risk": 1,\n   "size": "XS", "test_cmd": "grep -q \'RATE',
        '"value": 9, "risk": 1,\n   "size": "XS", "test_cmd": "grep -q \'RATE',
    )
    errors = check_job_spec(parse_spec(SPEC), parse_plan(plan), MONEY)
    assert any("pa-0001-w2" in e for e in errors)


def test_plan_without_workers_fails() -> None:
    errors = check_job_spec(parse_spec(SPEC), parse_plan("# Plan\n"), MONEY)
    assert any("worker" in e for e in errors)


def test_unflagged_money_path_fails() -> None:
    plan = PLAN.replace(
        '"files_in_scope": ["docs/runbook.md"]', '"files_in_scope": ["src/billing/x.py"]'
    )
    errors = check_job_spec(parse_spec(SPEC), parse_plan(plan), MONEY)
    assert any("src/billing/x.py" in e and "money" in e for e in errors)


def test_flagged_money_path_that_matches_passes() -> None:
    plan = PLAN.replace(
        '"files_in_scope": ["docs/runbook.md"]', '"files_in_scope": ["src/billing/x.py"]'
    )
    spec = SPEC.replace("## Money paths\nnone", "## Money paths\n- `src/billing/x.py`").replace(
        "- `docs/runbook.md`\n", "- `docs/runbook.md`\n- `src/billing/x.py`\n"
    )
    assert check_job_spec(parse_spec(spec), parse_plan(plan), MONEY) == []


def test_worker_scope_outside_spec_scope_fails() -> None:
    plan = PLAN.replace('"files_in_scope": ["docs/runbook.md"]', '"files_in_scope": ["README.md"]')
    errors = check_job_spec(parse_spec(SPEC), parse_plan(plan), MONEY)
    assert any("README.md" in e for e in errors)


def test_dependency_on_unknown_worker_fails() -> None:
    plan = PLAN.replace(
        '"must_fail_first": true}\n]', '"must_fail_first": true, "depends_on": ["nope"]}\n]'
    )
    errors = check_job_spec(parse_spec(SPEC), parse_plan(plan), MONEY)
    assert any("nope" in e for e in errors)


# --- owner decisions 2026-10-22: parallel writers and the verification ladder ---


def test_parallel_workers_with_overlapping_files_fail() -> None:
    plan = PLAN.replace(
        '"files_in_scope": ["docs/runbook.md"]', '"files_in_scope": ["docs/feature-map.md"]'
    )
    spec = SPEC.replace("- `docs/runbook.md`\n", "", 1)
    errors = check_job_spec(parse_spec(spec), parse_plan(plan), MONEY)
    assert any("disjoint" in e and "pa-0001-w1" in e and "pa-0001-w2" in e for e in errors)


def test_overlapping_workers_are_fine_when_ordered() -> None:
    plan = PLAN.replace(
        '"files_in_scope": ["docs/runbook.md"]', '"files_in_scope": ["docs/feature-map.md"]'
    )
    plan = plan.replace(
        '"must_fail_first": true}\n]', '"must_fail_first": true, "depends_on": ["pa-0001-w1"]}\n]'
    )
    errors = check_job_spec(parse_spec(SPEC), parse_plan(plan), MONEY)
    assert not any("disjoint" in e for e in errors)


def test_parallel_workers_need_pinned_interfaces() -> None:
    spec = SPEC.replace("## Interfaces\n- None shared: each worker edits its own doc file.\n\n", "")
    errors = check_job_spec(parse_spec(spec), parse_plan(PLAN), MONEY)
    assert any("Interfaces" in e for e in errors)


def test_a_single_writer_needs_no_interfaces_section() -> None:
    spec = SPEC.replace("## Interfaces\n- None shared: each worker edits its own doc file.\n\n", "")
    plan = PLAN.replace(
        '"must_fail_first": true}\n]', '"must_fail_first": true, "depends_on": ["pa-0001-w1"]}\n]'
    )
    assert check_job_spec(parse_spec(spec), parse_plan(plan), MONEY) == []


def test_every_criterion_needs_a_verify_entry() -> None:
    plan = PLAN.replace(',\n  {"criterion": "AC2", "level": 0, "why_not_higher": "same"}', "")
    errors = check_job_spec(parse_spec(SPEC), parse_plan(plan), MONEY)
    assert any("AC2" in e and "verify" in e for e in errors)


def test_level_zero_must_say_why_not_higher() -> None:
    plan = PLAN.replace('"why_not_higher": "same"', '"why_not_higher": ""')
    errors = check_job_spec(parse_spec(SPEC), parse_plan(plan), MONEY)
    assert any("why_not_higher" in e for e in errors)


def test_levels_not_built_yet_are_refused() -> None:
    plan = PLAN.replace(
        '{"criterion": "AC2", "level": 0, "why_not_higher": "same"}',
        '{"criterion": "AC2", "level": 1}',
    )
    errors = check_job_spec(parse_spec(SPEC), parse_plan(plan), MONEY)
    assert any("level 1" in e for e in errors)


def test_task_spec_has_a_verify_field_at_level_zero() -> None:
    t = _task()
    assert t.spec.verify.level == 0

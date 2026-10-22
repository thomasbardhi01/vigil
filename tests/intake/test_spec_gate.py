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

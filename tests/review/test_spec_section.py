"""#183: a `spec_section` evidence ref is checked against the parsed spec.md."""

from __future__ import annotations

import pytest

from vigild.jobs.artifacts import parse_spec
from vigild.review.evidence import spec_section_error

SPEC = """# Spec: x

## Goal
- one
- two
- three

## Non-goals
- nothing else

## Acceptance criteria
- AC1: it works test: `pytest -q`

## Files in scope
- `a.py`

## Files out of scope
- `b.py`
"""
BARE = "# Spec: x\n\n## Goal\nDo the one thing.\n\n## Acceptance criteria\n- AC1: ok\n"


@pytest.mark.parametrize(
    "ref", ["goal:1", "goal:3", "done_when", "non_goals", "files_out_of_scope"]
)
def test_a_ref_naming_a_real_part_of_the_spec_is_accepted(ref: str) -> None:
    assert spec_section_error(ref, parse_spec(SPEC)) is None


def test_goal_9_is_refused_when_the_spec_has_no_item_9() -> None:
    err = spec_section_error("goal:9", parse_spec(SPEC))
    assert err is not None and "Goal item 9" in err and "3 item" in err


def test_a_goal_that_is_prose_is_item_one() -> None:
    spec = parse_spec(BARE)
    assert spec_section_error("goal:1", spec) is None
    assert spec_section_error("goal:2", spec) is not None


@pytest.mark.parametrize("ref", ["non_goals", "files_out_of_scope"])
def test_a_section_the_spec_lacks_is_refused(ref: str) -> None:
    err = spec_section_error(ref, parse_spec(BARE))
    assert err is not None and "no" in err

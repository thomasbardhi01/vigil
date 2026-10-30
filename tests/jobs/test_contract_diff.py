"""The worker-contract diff and the changelog check (#38): pure functions, no model."""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from vigild.jobs.ownernote import contract_diff, spec_diff, unlisted_changes

WORKER: dict[str, Any] = {
    "task_id": "j-w1",
    "goal": "g",
    "why": "w",
    "value": 3,
    "risk": 1,
    "size": "XS",
    "test_cmd": "pytest -q a",
    "done_when": "d",
    "files_in_scope": ["a.py"],
    "out_of_scope": ["b.py"],
    "must_fail_first": True,
    "must_fail_first_reason": None,
    "depends_on": [],
    "labels": [],
    "max_cost_usd": 0.5,
    "verify_level": 0,
}
VERIFY = [{"criterion": "AC1", "level": 0, "why_not_higher": "x"}]


def _plan(workers: list[dict[str, Any]] | None = None, verify: Any = None) -> str:
    body = {
        "workers": [WORKER] if workers is None else workers,
        "verify": VERIFY if verify is None else verify,
    }
    return "# Plan\n\n## Workers\n```json\n" + json.dumps(body, indent=1) + "\n```\n"


def _with(**over: Any) -> str:
    return _plan([WORKER | over])


CHANGES: dict[str, Any] = {
    "test_cmd": "pytest -q b",
    "files_in_scope": ["a.py", "c.py"],
    "out_of_scope": [],
    "must_fail_first": False,
    "must_fail_first_reason": "tests only",
    "max_cost_usd": 1.0,
    "depends_on": ["j-w0"],
    "labels": ["docs"],
    "goal": "g2",
    "done_when": "d2",
    "verify_level": 1,
}


@pytest.mark.parametrize("field", list(CHANGES))
def test_contract_diff_each_field(field: str) -> None:
    got = contract_diff(_plan(), _with(**{field: CHANGES[field]}))
    assert got == [
        {
            "task_id": "j-w1",
            "field": field,
            "previous": WORKER[field],
            "amended": CHANGES[field],
        }
    ]


_OTHER = WORKER | {"task_id": "j-w2"}
_MORE = [*VERIFY, {"criterion": "AC2", "level": 0, "why_not_higher": "y"}]


@pytest.mark.parametrize(
    ("name", "previous", "amended", "task_id", "field"),
    [
        ("verify", _plan(), _plan(verify=_MORE), None, "verify"),
        ("task added", _plan(), _plan([WORKER, _OTHER]), "j-w2", "task"),
        ("task removed", _plan([WORKER, _OTHER]), _plan(), "j-w2", "task"),
    ],
)
def test_contract_diff_each_field_plan_level(
    name: str, previous: str, amended: str, task_id: str | None, field: str
) -> None:
    got = contract_diff(previous, amended)
    assert len(got) == 1
    assert got[0]["task_id"] == task_id and got[0]["field"] == field
    assert got[0]["previous"] != got[0]["amended"]


def test_contract_diff_each_field_ignores_why_value_risk_size() -> None:
    assert contract_diff(_plan(), _with(why="z", value=5, risk=2, size="M")) == []


def test_contract_diff_matches_tasks_by_task_id_only() -> None:
    a, b = WORKER, WORKER | {"task_id": "j-w2", "goal": "other"}
    assert contract_diff(_plan([a, b]), _plan([b, a])) == []


def test_contract_diff_interface() -> None:
    sig = inspect.signature(contract_diff, eval_str=True)
    assert str(sig) == "(previous_plan: str, amended_plan: str) -> list[dict]"
    got = contract_diff(_plan(), _with(goal="g2", test_cmd="x", out_of_scope=[]))
    assert len(got) == 3
    for e in got:
        assert isinstance(e, dict) and set(e) == {"task_id", "field", "previous", "amended"}
    for f, v in (("why", "z"), ("value", 5), ("risk", 3), ("size", "L")):
        assert contract_diff(_plan(), _with(**{f: v})) == []


def test_unlisted_interface() -> None:
    sig = inspect.signature(unlisted_changes, eval_str=True)
    assert str(sig) == "(changelog: str, contract: list[dict], spec_diff: str) -> list[str]"
    assert unlisted_changes("", [], "") == []
    got = unlisted_changes("", contract_diff(_plan(), _with(goal="g2")), "")
    assert isinstance(got, list) and got and all(isinstance(s, str) for s in got)


def test_unlisted_a_field_is_listed_by_its_name_as_a_whole_token() -> None:
    c = contract_diff(_plan(), _with(out_of_scope=[]))
    assert unlisted_changes("nothing", c, "") == ["j-w1: out_of_scope"]
    assert unlisted_changes("Changed OUT_OF_SCOPE.", c, "") == []
    assert unlisted_changes("changed out_of_scope_x", c, "") == ["j-w1: out_of_scope"]
    assert unlisted_changes("changed my_out_of_scope", c, "") == ["j-w1: out_of_scope"]


def test_unlisted_task_only_when_the_changelog_names_its_id() -> None:
    c = contract_diff(_plan(), _plan([WORKER, WORKER | {"task_id": "j-w2"}]))
    assert unlisted_changes("added a task", c, "") == ["j-w2: task added"]
    assert unlisted_changes("added task j-w2", c, "") == []
    assert unlisted_changes("added task j-w22", c, "") == ["j-w2: task added"]
    removed = contract_diff(_plan([WORKER, WORKER | {"task_id": "j-w2"}]), _plan())
    assert unlisted_changes("", removed, "") == ["j-w2: task removed"]


SPEC_A = "# S\n\n## Goal\nA\n\n## Non-goals\n- x\n\n## Rollback\nRevert.\n"


def test_unlisted_spec_section_comes_from_the_hunk_not_an_earlier_one() -> None:
    long = SPEC_A.replace("Revert.\n", "- filler\n" * 12 + "Revert.\n")
    amended = long.replace("A\n", "A2\n", 1).replace("Revert.", "Roll back.")
    d = spec_diff(long, amended, context=10**6)
    assert unlisted_changes("", [], d) == ["spec: Goal", "spec: Rollback"]
    assert unlisted_changes("the goal and rollback", [], d) == []
    # a hunked diff: the second hunk shows no heading, so the first's must not carry over
    hunked = spec_diff(long, amended)
    assert unlisted_changes("goal", [], hunked) == ["spec: (unknown)"]  # not "Goal"


def test_unlisted_a_changed_heading_names_itself() -> None:
    d = spec_diff(SPEC_A, SPEC_A.replace("## Rollback", "## Risks"), context=10**6)
    assert unlisted_changes("", [], d) == ["spec: Rollback", "spec: Risks"]

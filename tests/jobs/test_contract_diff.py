"""The worker-contract diff of an amendment (#38): pure, no model."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from vigild.jobs.ownernote import contract_diff, unlisted_changes

WORKERS: list[dict[str, Any]] = [
    {
        "task_id": "j-w1",
        "goal": "g1",
        "why": "w",
        "value": 3,
        "risk": 1,
        "size": "XS",
        "test_cmd": "pytest -q tests/a.py",
        "done_when": "d1",
        "files_in_scope": ["a.py", "tests/a.py"],
        "out_of_scope": ["b.py"],
        "labels": ["docs"],
    },
    {
        "task_id": "j-w2",
        "goal": "g2",
        "why": "w",
        "value": 3,
        "risk": 1,
        "size": "XS",
        "test_cmd": "pytest -q tests/b.py",
        "done_when": "d2",
        "files_in_scope": ["b.py", "tests/b.py"],
    },
]
VERIFY = [{"criterion": "AC1", "level": 0, "why_not_higher": "no property"}]


def _plan(workers: list[dict[str, Any]] | None = None, verify: Any = None) -> str:
    body = {"workers": WORKERS if workers is None else workers, "verify": verify or VERIFY}
    return "# Plan\n\n## Workers\n```json\n" + json.dumps(body, indent=1) + "\n```\n"


def _changed(**fields: Any) -> str:
    workers = copy.deepcopy(WORKERS)
    workers[0].update(fields)
    return _plan(workers)


def test_contract_diff_of_identical_plans_is_empty() -> None:
    assert contract_diff(_plan(), _plan()) == []


def test_contract_diff_names_the_one_changed_out_of_scope() -> None:
    got = contract_diff(_plan(), _changed(out_of_scope=["b.py", "c.py"]))
    assert got == [
        {
            "task_id": "j-w1",
            "field": "out_of_scope",
            "previous": ["b.py"],
            "amended": ["b.py", "c.py"],
        }
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("test_cmd", "pytest -q tests/other.py"),
        ("files_in_scope", ["a.py"]),
        ("must_fail_first", False),
        ("must_fail_first_reason", "tests only"),
        ("max_cost_usd", 0.5),
        ("depends_on", ["j-w2"]),
        ("labels", ["code"]),
        ("goal", "changed goal"),
        ("done_when", "changed done"),
        ("verify_level", 1),
    ],
)
def test_each_field_change_is_reported(field: str, value: Any) -> None:
    got = contract_diff(_plan(), _changed(**{field: value}))
    assert len(got) == 1 and got[0]["task_id"] == "j-w1" and got[0]["field"] == field
    assert got[0]["amended"] == value


def test_each_field_list_order_counts() -> None:
    got = contract_diff(_plan(), _changed(files_in_scope=["tests/a.py", "a.py"]))
    assert [e["field"] for e in got] == ["files_in_scope"]


def test_each_field_verify_list_and_added_or_removed_task() -> None:
    v2 = [{"criterion": "AC1", "level": 0, "why_not_higher": "different"}]
    (e,) = contract_diff(_plan(), _plan(verify=v2))
    assert e["task_id"] is None and e["field"] == "verify"
    (rem,) = contract_diff(_plan(), _plan(WORKERS[:1]))
    assert rem["task_id"] == "j-w2" and rem["field"] == "task" and rem["amended"] is None
    assert rem["previous"] is not None
    (add,) = contract_diff(_plan(WORKERS[:1]), _plan())
    assert add["task_id"] == "j-w2" and add["previous"] is None and add["amended"] is not None


DIFF = "--- a\n+++ b\n@@ -1,3 +1,4 @@\n ## Goal\n+more goal\n ## Rollback\n x\n"


def test_unlisted_names_a_contract_field_the_changelog_omits() -> None:
    contract = [{"task_id": "j-w1", "field": "out_of_scope", "previous": [], "amended": ["x"]}]
    assert unlisted_changes("- nothing", contract, "") == [
        "j-w1 out_of_scope: changed, not in the changelog"
    ]
    assert unlisted_changes("- widened OUT_OF_SCOPE", contract, "") == []
    assert unlisted_changes("- out_of_scope_x", contract, "") != []  # whole token only


def test_unlisted_names_a_spec_section_the_changelog_omits() -> None:
    (got,) = unlisted_changes("- changed the Rollback", [], DIFF.replace("+more goal", "+x"))
    assert got == "spec Goal: changed, not in the changelog"
    assert unlisted_changes("- Goal reworded", [], DIFF) == []
    assert unlisted_changes("", [], "") == []

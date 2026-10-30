"""contract_diff and unlisted_changes: pure, no model."""

from __future__ import annotations

import json

from tests.jobs.test_coord_loop import plan
from vigild.jobs.ownernote import contract_diff, unlisted_changes
from vigild.packets.fence import strip_fenced  # noqa: F401

J = "vi-0001"


def _edit(text: str, fn) -> str:  # type: ignore[no-untyped-def]
    head, rest = text.split("```json\n")
    body, tail = rest.split("\n```")
    raw = json.loads(body)
    fn(raw)
    return head + "```json\n" + json.dumps(raw) + "\n```" + tail


SPEC = "# S\n\n## Goal\nA\n\n## Non-goals\n- x\n\n## Risks\n- r\n"


def test_contract_diff_each_field_is_reported() -> None:
    old = plan(J)
    new = _edit(old, lambda r: r["workers"][0].update(out_of_scope=["src/**"], size="S"))
    d = contract_diff(old, new)
    assert {(x["task"], x["field"]) for x in d} == {
        (f"{J}-w1", "out_of_scope"),
        (f"{J}-w1", "size"),
    }
    assert contract_diff(old, old) == []


def test_contract_diff_each_field_added_and_removed_tasks() -> None:
    old = plan(J)
    new = _edit(old, lambda r: r["workers"].pop())
    (d,) = contract_diff(old, new)
    assert d["field"] == "task" and d["task"] == f"{J}-w2" and d["after"] is None


def test_unlisted_out_of_scope_change_is_flagged() -> None:
    old = plan(J)
    new = _edit(old, lambda r: r["workers"][0].update(out_of_scope=["secret/zone"]))
    u = unlisted_changes(SPEC, SPEC, old, new, "- nothing else changed\n")
    assert [(x["field"], x["where"]) for x in u] == [("out_of_scope", "plan")]
    assert unlisted_changes(SPEC, SPEC, old, new, "- widened out_of_scope\n") == []


def test_unlisted_task_needs_its_id_even_when_changelog_says_task() -> None:
    old = plan(J)
    new = _edit(old, lambda r: r["workers"].append({**r["workers"][0], "task_id": f"{J}-w3"}))
    assert len(unlisted_changes(SPEC, SPEC, old, new, "- added a task\n")) == 1
    assert unlisted_changes(SPEC, SPEC, old, new, f"- added task {J}-w3\n") == []
    assert len(unlisted_changes(SPEC, SPEC, old, new, f"- added {J}-w30\n")) == 1


def test_unlisted_spec_section_comes_from_line_numbers() -> None:
    new = SPEC.replace("## Goal\nA\n", "## Goal\nA\nB\n").replace("- r\n", "- r\n- q\n")
    u = unlisted_changes(SPEC, new, None, None, "- reworded the goal\n")
    assert [x["section"] for x in u] == ["Risks"]  # not Goal, carried from the first hunk
    assert unlisted_changes(SPEC, new, None, None, "goal, risks") == []

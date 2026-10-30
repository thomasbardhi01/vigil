"""The owner's replan note (owner spec, 2026-10-25): its size cap, the diff the
spec item shows, and the lines of the note that go to the hidden-test author.

None of this involves a model. The note comes only through the admin API, so it
is the owner's text: it is not fenced as untrusted."""

from __future__ import annotations

import difflib
import re
from typing import Any

from vigild.jobs.artifacts import MD_PROV, parse_plan

NOTE_MAX_BYTES = 8192

HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
NUMBERED = re.compile(r"^([ \t]*)\d{1,3}[.)][ \t]+(.*)$")
AUTHOR = re.compile(r"\bauthor\b", re.I)
BULLET = re.compile(r"^[ \t]*[-*•◦][ \t]")


def spec_body(text: str) -> str:
    """A stored spec without its provenance comment."""
    return MD_PROV.sub("", text)


def spec_diff(
    previous: str, amended: str, baseline: str = "previously approved", context: int = 3
) -> str:
    """A unified diff of the baseline spec (the last approved one, or "current draft,
    never approved") against the amended one ('' when they are the same text),
    ignoring the provenance comments."""
    old = spec_body(previous).splitlines()
    new = spec_body(amended).splitlines()
    lines = difflib.unified_diff(
        old, new, f"spec.md ({baseline})", "spec.md (amended)", lineterm="", n=context
    )
    out = "\n".join(lines)
    return out + "\n" if out else ""


def _section(lines: list[str], i: int) -> int:
    """The index one past the section that starts at line i. A heading runs to the
    next heading of its level or above. A numbered item runs to the next heading or
    numbered item at its indent or above. Its body is its indented and bullet lines
    and, until it has had one, its plain lines (a plain line after bullets is the
    note's own text, not the item's). Blank lines never end it."""
    h = HEADING.match(lines[i])
    j = i + 1
    if h:
        level = len(h.group(1))
        while j < len(lines):
            m = HEADING.match(lines[j])
            if m and len(m.group(1)) <= level:
                break
            j += 1
        return j
    indent = len(NUMBERED.match(lines[i]).group(1).expandtabs())  # type: ignore[union-attr]
    structured = False
    while j < len(lines):
        line = lines[j]
        if not line.strip():
            pass  # a blank line never ends an item: only the next item or heading does
        elif HEADING.match(line):
            break
        else:
            lead = len(line) - len(line.lstrip())
            if NUMBERED.match(line) and lead <= indent:
                break
            if BULLET.match(line) or lead > indent:
                structured = True
            elif structured:
                break
        j += 1
    return j


def author_contract(note: str) -> str:
    """The lines of the note under a heading or a numbered item whose title has the
    word "author" (for example "Hidden-test author contract"; not "authorization"),
    each section from its title line to its end; several are joined by a blank
    line. When no title has it, or the matched sections have no body, the whole note."""
    lines = note.splitlines()
    sections: list[str] = []
    i = 0
    while i < len(lines):
        h = HEADING.match(lines[i])
        n = NUMBERED.match(lines[i])
        title = h.group(2) if h else n.group(2) if n else None
        if title is not None and AUTHOR.search(title):
            j = _section(lines, i)
            if any(x.strip() for x in lines[i + 1 : j]):
                sections.append("\n".join(lines[i:j]).rstrip())
            i = j
        else:
            i += 1
    return "\n\n".join(sections) if sections else note.strip()


# --- the worker-contract diff and what the changelog doesn't list (#38) -----------------------

CONTRACT_FIELDS = (
    "test_cmd",
    "files_in_scope",
    "out_of_scope",
    "must_fail_first",
    "must_fail_first_reason",
    "max_cost_usd",
    "depends_on",
    "labels",
    "goal",
    "done_when",
    "verify_level",
)
HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
SPEC_HEADING = re.compile(r"^##[ \t]+(.*?)[ \t]*$")


def contract_diff(previous_plan: str, amended_plan: str) -> list[dict[str, Any]]:
    """Each worker-contract field that differs between two plan.md texts, as entries
    {task_id, field, previous, amended}. Tasks are matched by task_id only; a task in one
    plan only is one entry with field "task"; the plan-level `verify` list is one entry
    with task_id None. Only the fields in CONTRACT_FIELDS count."""
    old, new = parse_plan(previous_plan), parse_plan(amended_plan)
    before = {w.task_id: w for w in old.workers}
    after = {w.task_id: w for w in new.workers}
    out: list[dict[str, Any]] = []
    for tid, w in after.items():
        if tid not in before:
            out.append({"task_id": tid, "field": "task", "previous": None, "amended": tid})
            continue
        for f in CONTRACT_FIELDS:
            a, b = getattr(before[tid], f), getattr(w, f)
            if a != b:
                out.append({"task_id": tid, "field": f, "previous": a, "amended": b})
    for tid in before:
        if tid not in after:
            out.append({"task_id": tid, "field": "task", "previous": tid, "amended": None})
    va = [v.model_dump() for v in old.verify]
    vb = [v.model_dump() for v in new.verify]
    if va != vb:
        out.append({"task_id": None, "field": "verify", "previous": va, "amended": vb})
    return out


def _names(changelog: str, name: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(name)}(?!\w)", changelog, re.I) is not None


def _changed_sections(diff_text: str) -> list[str]:
    """The `##` section of each changed spec line, from the headings the diff itself
    shows above it in its own hunk (a full-context diff shows them all); never one
    carried over from an earlier hunk. A change with none above it is "(unknown)"."""
    out: list[str] = []
    heading: str | None = None
    for line in diff_text.splitlines():
        if HUNK.match(line):
            heading = None
            continue
        if not line or line.startswith(("--- ", "+++ ")):
            continue
        m = SPEC_HEADING.match(line[1:])
        if m and line[0] in " +":
            heading = m.group(1)
        if line[0] in "+-":
            out.append(m.group(1) if m else heading or "(unknown)")
    return list(dict.fromkeys(out))


def unlisted_changes(changelog: str, contract: list[dict[str, Any]], spec_diff: str) -> list[str]:
    """The changes the coord's changelog doesn't name: a contract field whose name is
    not a whole token of it, a task added or removed whose id it doesn't name, and each
    spec section changed whose heading it doesn't name. `spec_diff` should be a
    full-context diff so each change shows its section."""
    out: list[str] = []
    for e in contract:
        field, tid = e["field"], e["task_id"]
        if field == "task":
            if not _names(changelog, str(tid)):
                out.append(f"{tid}: task {'added' if e['previous'] is None else 'removed'}")
        elif not _names(changelog, field):
            out.append(f"{tid}: {field}" if tid else field)
    for section in _changed_sections(spec_diff):
        if not _names(changelog, section):
            out.append(f"spec: {section}")
    return out

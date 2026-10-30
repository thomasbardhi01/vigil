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


def spec_diff(previous: str, amended: str, baseline: str = "previously approved") -> str:
    """A unified diff of the baseline spec (the last approved one, or "current draft,
    never approved") against the amended one ('' when they are the same text),
    ignoring the provenance comments."""
    old = spec_body(previous).splitlines()
    new = spec_body(amended).splitlines()
    lines = difflib.unified_diff(
        old, new, f"spec.md ({baseline})", "spec.md (amended)", lineterm=""
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


def contract_diff(previous_plan: str, amended_plan: str) -> list[dict[str, Any]]:
    """Every changed worker-contract field between two plan.md texts, matched by
    task_id: {"task_id", "field", "previous", "amended"}. A task in only one plan is
    one entry with field "task"; a differing `verify` list is one with task_id None."""
    old, new = parse_plan(previous_plan), parse_plan(amended_plan)
    a = {w.task_id: w.model_dump(mode="json") for w in old.workers}
    b = {w.task_id: w.model_dump(mode="json") for w in new.workers}
    out: list[dict[str, Any]] = []
    for tid in [*a, *(t for t in b if t not in a)]:
        if tid not in b or tid not in a:
            out.append(
                {"task_id": tid, "field": "task", "previous": a.get(tid), "amended": b.get(tid)}
            )
            continue
        for f in CONTRACT_FIELDS:
            if a[tid][f] != b[tid][f]:
                out.append(
                    {"task_id": tid, "field": f, "previous": a[tid][f], "amended": b[tid][f]}
                )
    va = [v.model_dump(mode="json") for v in old.verify]
    vb = [v.model_dump(mode="json") for v in new.verify]
    if va != vb:
        out.append({"task_id": None, "field": "verify", "previous": va, "amended": vb})
    return out


def _names(changelog: str, word: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(word)}(?![\w])", changelog, re.I) is not None


def unlisted_changes(changelog: str, contract: list[dict[str, Any]], spec_diff: str) -> list[str]:
    """The changes the changelog doesn't list. A contract change is listed when the
    changelog has its field name as a whole token; a spec change when it names the `##`
    section the diff changes (a change before any heading seen in the diff is "spec")."""
    out = [
        f"{c['task_id'] or 'plan'} {c['field']}: changed, not in the changelog"
        for c in contract
        if not _names(changelog, str(c["field"]))
    ]
    section = ""
    changed: list[str] = []
    for line in spec_diff.splitlines():
        if line.startswith(("---", "+++", "@@")):
            continue
        text = line[1:]
        if text.startswith("## "):
            section = text[3:].strip()
        if line[:1] in ("+", "-") and section not in changed:
            changed.append(section)
    for sec in changed:
        if not sec or not _names(changelog, sec):
            out.append(f"spec {sec or '(no section)'}: changed, not in the changelog")
    return out

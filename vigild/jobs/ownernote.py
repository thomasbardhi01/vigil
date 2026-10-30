"""The owner's replan note (owner spec, 2026-10-25): its size cap, the diff the
spec item shows, and the lines of the note that go to the hidden-test author.

None of this involves a model. The note comes only through the admin API, so it
is the owner's text: it is not fenced as untrusted."""

from __future__ import annotations

import difflib
import re

from vigild.jobs.artifacts import MD_PROV

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


# --- what an amendment changed that the coord did not say ---------------------------------------

PLAN_FIELDS = (
    "goal", "why", "value", "risk", "size", "test_cmd", "done_when", "files_in_scope",
    "out_of_scope", "must_fail_first", "must_fail_first_reason", "depends_on", "labels",
    "max_cost_usd", "verify_level",
)  # fmt: skip


def _workers(plan_text: str) -> dict[str, dict[str, object]]:
    """plan.md's workers by task id ({} when it has none that parse)."""
    from vigild.jobs.artifacts import parse_plan

    out: dict[str, dict[str, object]] = {}
    for w in parse_plan(spec_body(plan_text)).workers:
        out[w.task_id] = w.model_dump()
    return out


def contract_diff(previous_plan: str, amended_plan: str) -> list[dict[str, object]]:
    """Every worker-contract change between two plans: a task added or removed
    (`field` "task") or one field of a task in both, as {task, field, before, after}."""
    old, new = _workers(previous_plan), _workers(amended_plan)
    # a re-plan renumbers its workers, so pair them: by id, then by goal
    pairs: dict[str, str] = {t: t for t in old if t in new}
    for t in old:
        if t not in pairs:
            g = next(
                (n for n in new if n not in pairs.values() and new[n]["goal"] == old[t]["goal"]),
                None,
            )
            if g is not None:
                pairs[t] = g
    out: list[dict[str, object]] = []
    for tid in sorted(old.keys() - pairs.keys()):
        out.append({"task": tid, "field": "task", "before": old[tid]["goal"], "after": None})
    for tid in sorted(new.keys() - set(pairs.values())):
        out.append({"task": tid, "field": "task", "before": None, "after": new[tid]["goal"]})
    for o, n in pairs.items():
        for f in PLAN_FIELDS:
            before = old[o].get(f)
            if f == "depends_on" and isinstance(before, list):
                before = [pairs.get(str(d), d) for d in before]
            if before != new[n].get(f):
                out.append({"task": n, "field": f, "before": before, "after": new[n].get(f)})
    return out


def _heading_at(lines: list[str], i: int) -> str:
    """The `##` section that line i of a spec is in (by its position in the full text)."""
    for k in range(min(i, len(lines) - 1), -1, -1):
        if lines[k].startswith("## "):
            return lines[k][3:].strip()
    return "(preamble)"


def spec_changes(previous: str, amended: str) -> list[dict[str, object]]:
    """The spec's changed hunks as {section, before, after}. A hunk's section comes from
    its line numbers against the full spec text, never from a heading an earlier hunk
    carried over."""
    old = spec_body(previous).splitlines()
    new = spec_body(amended).splitlines()
    out: list[dict[str, object]] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
        None, old, new, autojunk=False
    ).get_opcodes():
        if tag == "equal":
            continue
        section = _heading_at(old, i1) if tag == "delete" else _heading_at(new, j1)
        out.append({"section": section, "before": old[i1:i2], "after": new[j1:j2]})
    return out


def _norm(text: str) -> str:
    return re.sub(r"[\s_`]+", " ", text).strip().lower()


def unlisted_changes(
    previous_spec: str,
    amended_spec: str,
    previous_plan: str | None,
    amended_plan: str | None,
    changelog: str,
    note: str = "",
) -> list[dict[str, object]]:
    """The changes the coord's changelog (or the owner's note) does not mention: a spec
    hunk whose section name or changed text is not in them, a contract field whose name
    or changed value is not, and a task added or removed (`field` "task") unless the
    changelog names its task id."""
    said = _norm(changelog + "\n" + note)
    out: list[dict[str, object]] = []
    for c in spec_changes(previous_spec, amended_spec):
        lines = [str(x) for x in (*c["before"], *c["after"])]  # type: ignore[misc]
        texts = [_norm(x.lstrip("-* ")) for x in lines if x.strip()]
        if _norm(str(c["section"])).rstrip("s") in said or any(t and t in said for t in texts):
            continue
        out.append(
            {"where": "spec", "section": c["section"], "before": c["before"], "after": c["after"]}
        )
    if previous_plan is None or amended_plan is None:
        return out
    for d in contract_diff(previous_plan, amended_plan):
        if d["field"] == "task":
            if not re.search(rf"(?<![\w-]){re.escape(str(d['task']))}(?![\w-])", changelog):
                out.append({"where": "plan", **d})
            continue
        vals = {
            _norm(str(v))
            for side in (d["before"], d["after"])
            for v in (side if isinstance(side, list) else [side])
        }
        if _norm(str(d["field"])) in said or any(v and len(v) > 3 and v in said for v in vals):
            continue
        out.append({"where": "plan", **d})
    return out

"""#183: a `spec_section` evidence ref, checked against the parsed spec.md."""

from __future__ import annotations

import json
import re

from pydantic import ValidationError

from vigild.contract.models import Evidence
from vigild.jobs.artifacts import SpecDoc
from vigild.redact import redact

_SECTION = {
    "done_when": ("Acceptance criteria", "done-when (Acceptance criteria)"),
    "non_goals": ("Non-goals", "Non-goals"),
    "files_out_of_scope": ("Files out of scope", "Files out of scope"),
}
_ITEM = re.compile(r"^(?:[-*]|\d+[.)])\s+\S")  # top level only: no indent


def _key(name: str) -> str:
    return re.sub(r"[\s_-]+", " ", name.strip().lower())


def _section(spec: SpecDoc, name: str) -> str:
    return next((b for h, b in spec.sections.items() if _key(h) == _key(name)), "")


def goal_items(spec: SpecDoc) -> int:
    """Goal items: its list entries, or 1 for a Goal written as prose, or 0 for none."""
    body = _section(spec, "Goal")
    n = sum(1 for ln in body.splitlines() if _ITEM.match(ln))
    return n or (1 if body.strip() else 0)


def spec_section_error(ref: str, spec: SpecDoc) -> str | None:
    """Why a normalised ref (`goal:N`, `done_when`, `non_goals`, `files_out_of_scope`) names
    nothing in this spec, or None when it names something that is there."""
    if ref.startswith("goal:"):
        n, have = int(ref[5:]), goal_items(spec)
        if n > have:
            return f"the spec has no Goal item {n} (it has {have} item(s))"
        return None
    name, label = _SECTION[ref]
    if not _section(spec, name).strip():
        return f"the spec has no {label} section"
    return None


def triage_evidence(raw: object, spec: SpecDoc) -> tuple[object, list[tuple[int, str]]]:
    """A reviewer's or auditor's answer with each finding whose evidence fails validation (or
    names nothing in the spec) kept at its severity and marked `evidence_invalid` with the
    error, instead of failing the whole file (#183). Also the list of (index, error). The
    marks are vigild's: any the model wrote are stripped. A finding with no evidence at all,
    and an answer that is not a findings list, are left for the model to reject."""
    if not isinstance(raw, dict) or not isinstance(raw.get("findings"), list):
        return raw, []
    bad: list[tuple[int, str]] = []
    findings: list[object] = []
    for i, f in enumerate(raw["findings"]):
        if not isinstance(f, dict):
            findings.append(f)
            continue
        f = {k: v for k, v in f.items() if k not in ("evidence_invalid", "evidence_error")}
        ev = f.get("evidence")
        if ev is not None:
            why = _evidence_error(ev, spec)
            if why is not None:
                why = redact(f"evidence {json.dumps(ev, default=str)[:200]}: {why}")[:900]
                f = {**f, "evidence": None, "evidence_invalid": True, "evidence_error": why}
                bad.append((i, why))
        findings.append(f)
    return {**raw, "findings": findings}, bad


def _evidence_error(ev: object, spec: SpecDoc) -> str | None:
    try:
        e = Evidence.model_validate(ev)
    except ValidationError as err:
        return "; ".join(str(x["msg"]) for x in err.errors())
    if e.kind == "spec_section":
        return spec_section_error(e.ref, spec)
    return None

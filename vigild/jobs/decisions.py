"""A job's decisions log (ADR-0005 part 4): the vault artifact `decisions.jsonl`.

Append only: a new version holds the old text unchanged plus the new lines. The coord
writes `.vigil/<job>/decisions.jsonl` in its clone and vigild reads it as a vault blob;
vigild appends its own lines; a worker's copy is never read. Every line passes the
`DecisionLine` model and `redact`. The packets of the replan coord, the worker, the fix
round and the reviewer get the log fenced as data (never the auditor's).
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import ValidationError

from vigild.contract.models import DecisionLine
from vigild.db import Store, iso
from vigild.provenance import Provenance
from vigild.redact import redact

NAME = "decisions.jsonl"
SECTION_CHARS = 4000
MAX_COORD_LINES = 200  # a result's file is read this far; the rest counts as dropped


def _render(line: DecisionLine) -> str:
    return json.dumps(line.model_dump(), sort_keys=True)


def _append(store: Store, job_id: str, new: list[DecisionLine]) -> None:
    """A new version: the old text unchanged plus the new lines. Its provenance is
    `claude` if any line in it, old or new, is the coord's, else `human`."""
    if not new:
        return
    art = store.get_artifact(job_id, NAME)
    old = art.content if art is not None else ""
    if old and not old.endswith("\n"):
        old += "\n"
    content = old + "".join(_render(x) + "\n" for x in new)
    by_coord = any(json.loads(r)["by"] == "coord" for r in content.splitlines() if r.strip())
    store.add_artifact(job_id, NAME, content, Provenance.CLAUDE if by_coord else Provenance.HUMAN)


def add(store: Store, job_id: str, by: Literal["coord", "vigild"], kind: str, text: str) -> None:
    """vigild's own line. The text is cut to the model's limit, then redacted."""
    line = DecisionLine(
        ts=iso(),
        by=by,
        kind=kind,
        text=str(redact(text))[:300],
    )
    _append(store, job_id, [line])


def ingest_coord(store: Store, job_id: str, raw: str) -> tuple[int, int]:
    """The coord's file, read as a vault blob: valid lines are stored with `by` set to
    `coord`; the rest are dropped. Returns (kept, dropped)."""
    kept: list[DecisionLine] = []
    dropped = 0
    rows = [r for r in raw.splitlines() if r.strip()]
    dropped += max(0, len(rows) - MAX_COORD_LINES)
    for row in rows[:MAX_COORD_LINES]:
        try:
            data = json.loads(row)
            if not isinstance(data, dict):
                raise ValueError("not an object")
            data["by"] = "coord"
            data["ts"] = iso()
            line = DecisionLine.model_validate(data)
        except ValueError, ValidationError:
            dropped += 1
            continue
        kept.append(line.model_copy(update={"text": redact(line.text)}))
    _append(store, job_id, kept)
    return len(kept), dropped


def section(store: Store, job_id: str, cap: int = SECTION_CHARS) -> dict[str, str]:
    """The log as a packet's fenced `decisions` entry, newest last: the oldest lines are
    dropped to fit `cap`, with a note. Empty when the job has no log."""
    art = store.get_artifact(job_id, NAME)
    if art is None:
        return {}
    rows = [r for r in art.content.splitlines() if r.strip()]
    texts: list[str] = []
    for r in rows:
        d: dict[str, Any] = json.loads(r)
        texts.append(f"{d['ts']} {d['by']} {d['kind']}: {d['text']}")
    if not texts:
        return {}
    kept: list[str] = []
    size = 0
    for t in reversed(texts):
        if size + len(t) + 1 > cap:
            break
        kept.insert(0, t)
        size += len(t) + 1
    cut = len(texts) - len(kept)
    note = f"({cut} older line{'s' if cut != 1 else ''} dropped)\n" if cut else ""
    return {"decisions": note + "\n".join(kept)}

"""Executor evidence on a worker report (#106): image digest, heads, lineage
and a screened failure diagnostic. Built only from vigild's own records; a
worker's own `executor` field is dropped before the report is read."""

from __future__ import annotations

import json
import re
from typing import Any

from vigild.redact import redact

UNKNOWN_OUTPUT = "withheld (unknown output)"
MAX_BYTES = 2000
_CAP = re.compile(r"out of (budget|cap)|budget.{0,20}(exceed|cap)|over (the )?cap", re.I)
_REFUSED = re.compile(r"refus", re.I)


def without_executor(raw: str) -> str:
    """The report's JSON without any `executor` key the worker wrote."""
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(doc, dict):
        doc.pop("executor", None)
        return json.dumps(doc)
    return raw


def failure_diagnostic(status: str, exit_code: int | None, error: str | None) -> str | None:
    """None unless the session failed. A known kind (timeout, out of cap, refused,
    crash with an exit code) gets a redacted line of at most 2,000 bytes; any
    other output is withheld whole."""
    if status == "done":
        return None
    text = error or ""
    if status == "timeout":
        kind = "timeout"
    elif _CAP.search(text):
        kind = "out of cap"
    elif _REFUSED.search(text):
        kind = "refused"
    elif exit_code is not None:
        kind = f"crash (exit {exit_code})"
    else:
        return UNKNOWN_OUTPUT
    line = f"{kind}: {redact(text)}"
    return line.encode()[:MAX_BYTES].decode(errors="ignore")


def executor_block(
    detail: dict[str, Any], end_head: str, failure: str | None = None
) -> dict[str, Any]:
    """The `executor` block, from the session's stored launch record."""
    return {
        "image_digest": detail.get("image_digest"),
        "base_head": detail.get("base_sha"),
        "launch_head": detail.get("launch_head"),
        "end_head": end_head,
        "lineage": detail.get("lineage"),
        "failure_diagnostic": failure,
    }

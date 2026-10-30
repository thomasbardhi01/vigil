"""Why a worker session on a local backend failed (#181): its cause, read from
vigild's own records only. The gateway's `model_calls` rows (status, latency,
spend), its `upstream_error` events (an HTTP status or a transport error class),
and the redacted CLI stderr tail. Never from text a model wrote as its answer."""

from __future__ import annotations

import json
from typing import Any

from vigild.db import Store

CONTEXT_WORDS = ("context size", "context length", "context window", "context_overflow",
                 "prompt is too long", "too many tokens")  # fmt: skip
UNREACHABLE_STDERR = ("econnrefused", "enotfound", "connection refused", "getaddrinfo",
                      "name or service not known", "unreachable")  # fmt: skip
TIMEOUT_STDERR = ("etimedout", "timed out", "timeout")


def _events(store: Store, session_id: str) -> list[dict[str, Any]]:
    rows = store.q(
        "SELECT data FROM events WHERE session_id=? AND type='upstream_error' ORDER BY id",
        (session_id,),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            d = json.loads(r["data"])
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def calls_summary(store: Store, session_id: str) -> dict[str, Any]:
    """Count, statuses with counts, max latency, metered spend: the gateway's calls."""
    rows = store.q(
        "SELECT status, latency_ms, cost_usd FROM model_calls WHERE session_id=?", (session_id,)
    )
    statuses: dict[str, int] = {}
    for r in rows:
        k = str(r["status"])
        statuses[k] = statuses.get(k, 0) + 1
    count = len(rows)
    transport: dict[str, int] = {}
    for e in _events(store, session_id):
        if isinstance(e.get("status"), int):
            statuses[str(e["status"])] = statuses.get(str(e["status"]), 0) + 1
            count += 1
        elif e.get("error"):
            name = str(e["error"])
            transport[name] = transport.get(name, 0) + 1
    out: dict[str, Any] = {
        "count": count,
        "statuses": statuses,
        "max_latency_ms": max((int(r["latency_ms"] or 0) for r in rows), default=0),
        "spend_usd": round(sum(float(r["cost_usd"] or 0) for r in rows), 6),
    }
    if transport:
        out["transport_errors"] = transport
    return out


def _http_cause(status: int, message: str) -> str:
    low = message.lower()
    if any(w in low for w in CONTEXT_WORDS):
        return "context_overflow"
    if status in (400, 404) and "model" in low:
        return "wrong_model"
    return f"http_{status}"


def cause_of(store: Store, session_id: str, stderr: str, calls: dict[str, Any]) -> str:
    events = _events(store, session_id)
    http = [e for e in events if isinstance(e.get("status"), int)]
    if http:
        last = http[-1]
        return _http_cause(int(last["status"]), str(last.get("message") or ""))
    bad = [int(k) for k in calls["statuses"] if k.isdigit() and int(k) != 200]
    if bad:
        return _http_cause(max(bad), "")
    names = [str(e["error"]) for e in events if e.get("error")]
    if any("Timeout" in n for n in names):
        return "timeout"
    if names:
        return "unreachable"  # a refused connection, DNS, or a dropped one
    low = stderr.lower()
    if any(w in low for w in CONTEXT_WORDS):
        return "context_overflow"
    if any(w in low for w in UNREACHABLE_STDERR):
        return "unreachable"
    if any(w in low for w in TIMEOUT_STDERR):
        return "timeout"
    if calls["count"] and set(calls["statuses"]) == {"200"}:
        return "client_side_stop"
    return "unknown"


def local_failure(store: Store, session_id: str, backend: str) -> dict[str, Any]:
    """The page entry's `backend`, `cause` and `calls` for a failed local session."""
    s = store.get_session(session_id)
    stderr = str(s.detail.get("cli_stderr_tail") or "")
    calls = calls_summary(store, session_id)
    return {"backend": backend, "cause": cause_of(store, session_id, stderr, calls), "calls": calls}

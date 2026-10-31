"""Why a worker session on a local backend failed (#181): its cause, read from
vigild's own records only. The gateway's `model_calls` rows (status, latency,
spend), its `upstream_error` events (an HTTP status or a transport error class),
and the redacted CLI stderr tail. Never from text a model wrote as its answer."""

from __future__ import annotations

import json
from typing import Any

from vigild.db import Store

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
        elif e.get("transport"):
            name = str(e["transport"])
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


def _http_cause(e: dict[str, Any]) -> str:
    if e.get("context"):
        return "context_overflow"
    if e.get("model") and e["status"] in (400, 404):
        return "wrong_model"
    return f"http_{e['status']}"


def cause_of(store: Store, session_id: str, stderr: str, calls: dict[str, Any]) -> str:
    """The latest failure evidence wins (events are in time order). When every
    gateway call was 200 and no error event exists, the CLI stopped it itself,
    whatever its stderr says (stderr is only a hint when the gateway saw nothing)."""
    events = _events(store, session_id)
    for e in reversed(events):
        if isinstance(e.get("status"), int):
            return _http_cause(e)
        if e.get("transport"):
            return "timeout" if "Timeout" in str(e["transport"]) else "unreachable"
    bad = [int(k) for k in calls["statuses"] if k.isdigit() and int(k) != 200]
    if bad:
        return _http_cause({"status": max(bad)})
    if calls["count"] and set(calls["statuses"]) == {"200"}:
        return "client_side_stop"
    low = stderr.lower()
    if any(w in low for w in UNREACHABLE_STDERR):
        return "unreachable"
    if any(w in low for w in TIMEOUT_STDERR):
        return "timeout"
    return "unknown"


def local_failure(store: Store, session_id: str, backend: str) -> dict[str, Any]:
    """The page entry's `backend`, `cause` and `calls` for a failed local session."""
    s = store.get_session(session_id)
    stderr = str(s.detail.get("cli_stderr_tail") or "")
    calls = calls_summary(store, session_id)
    return {"backend": backend, "cause": cause_of(store, session_id, stderr, calls), "calls": calls}

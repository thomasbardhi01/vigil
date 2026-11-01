"""The gateway's prefix holds on a real Claude Code worker (owner, 2026-11-01, after vi-0019
w3): a Sonnet worker in the executor image makes several tool calls through vigild's real
gateway, and every call from the second on is held at the read rate for what the previous
call cached (pytest -m "docker and live"; Sonnet, a few cents).

Done when (#262): `hold_reason=prefix` from call 2 on, each call's input hold within 1.5x its
actual input cost, and no overshoot."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from tests.security.test_guard_in_container import vigild as vigild
from vigild.executors.base import SessionSpec
from vigild.executors.runtime import DockerRuntime
from vigild.jobs.model import Role
from vigild.metering.calls import CallUsage
from vigild.server import Vigild

pytestmark = [
    pytest.mark.docker,
    pytest.mark.live,
    pytest.mark.parametrize("executor_image", ["generic"], indirect=True),
]

PRESET, MODEL = "claude-sonnet", "claude-sonnet-5-5"
MAX_OUT = 4096  # the CLI's per-call output cap: the hold's output part is this, at most
PROMPT = (
    "This is a test of how the gateway holds budget across tool calls. Make exactly six "
    "tool calls, one per turn, never two at once: first use Bash to run `ls -la`, then use "
    "Read on five different files in this repository, one at a time. Do not edit or write "
    "anything. After the sixth call, reply with the single word DONE and stop."
)


def test_a_worker_s_calls_are_held_at_the_prefix_rate_from_the_second_on(
    runtime: DockerRuntime, make_spec: Callable[..., SessionSpec], vigild: Vigild
) -> None:
    v = vigild
    spec = make_spec(Role.WORKER)
    spec.preset, spec.model = PRESET, MODEL
    spec.max_turns, spec.max_budget_usd, spec.max_output_tokens = 12, 0.80, MAX_OUT
    spec.packet = PROMPT
    sess = v.store.create_session(None, spec.role, backend_preset=PRESET)
    spec.session_id = sess.id
    v.budget.reserve(session_id=sess.id, task_id=None, amount=1.00, purpose="prefix-live")
    token = v.gateway.issue_token(sess.id, "thomasbardhi01/vigil", PRESET)
    try:
        out = runtime.run(spec, token, lambda e: None)
    finally:
        v.gateway.revoke(sess.id)
        v.budget.settle_session(sess.id)
    rows = v.store.q(
        "SELECT id, model, hold_usd, hold_reason, cost_usd, tokens_in, tokens_cache_read,"
        " tokens_cache_write_5m, tokens_cache_write_1h, tokens_out FROM model_calls"
        " WHERE session_id=? ORDER BY id",
        (sess.id,),
    )
    misses = [e.data for e in v.store.events(session_id=sess.id) if e.type == "prefix_miss"]
    excess = [e.data for e in v.store.events(session_id=sess.id) if e.type == "settle_excess"]
    prices = v.gateway.prices
    table = []
    for r in rows:
        out_hold = prices.cost(r["model"], CallUsage(tokens_out=MAX_OUT))
        out_cost = prices.cost(r["model"], CallUsage(tokens_out=r["tokens_out"]))
        table.append({
            "id": r["id"], "reason": r["hold_reason"],
            "input_hold": round(r["hold_usd"] - out_hold, 5),
            "input_actual": round(r["cost_usd"] - out_cost, 5),
            "read": r["tokens_cache_read"], "write": r["tokens_cache_write_5m"],
            "in": r["tokens_in"], "out": r["tokens_out"],
        })  # fmt: skip
    print(json.dumps({"status": out.status, "calls": table, "prefix_miss": misses,
                      "settle_excess": excess,
                      "spend": round(sum(r["cost_usd"] for r in rows), 5)}, indent=1))  # fmt: skip
    session_calls = table
    assert len(session_calls) >= 4, out
    assert all(t["reason"] == "prefix" for t in session_calls[1:]), misses
    assert all(t["input_hold"] <= 1.5 * t["input_actual"] + 1e-4 for t in session_calls[1:])
    assert not excess

"""Replay of A1's 25-call sequence (session s-a3ccbbac44, 2026-10-31, $0.80) through the
precise holds (owner ruling R23, 2026-10-31 (#1)). The token counts are the session's
`model_calls` rows (tokens_in, cache_read, cache_write_5m, out); byte lengths are tokens
times the ratio the refused call showed (about 5.8 characters per token: `chars / 3` read
77k tokens as 149k). Run `uv run pytest tests/gateway/test_a1_replay.py -s` for the table."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from tests.gateway.test_gateway import _session, budget, client, gw  # noqa: F401
from tests.gateway.test_precise_holds import MODEL, Upstream, upstream  # noqa: F401
from vigild.budget import Budget
from vigild.db import Store
from vigild.gateway.service import Gateway
from vigild.metering.calls import CallUsage

# (tokens_in, cache_read, cache_write_5m, tokens_out), in order
A1 = [
    (2, 0, 48767, 165), (2, 48767, 1425, 324), (2, 50192, 3261, 174), (2, 53453, 1523, 150),
    (2, 54976, 1372, 2853), (2, 56348, 3053, 1601), (2, 59401, 1809, 115), (2, 61210, 185, 115),
    (2, 61395, 185, 102), (2, 61580, 179, 93), (2, 61759, 222, 180), (2, 61981, 1878, 138),
    (2, 63859, 746, 779), (2, 64605, 1464, 292), (2, 66069, 609, 206), (2, 66678, 1200, 135),
    (2, 67878, 1376, 557), (2, 69254, 681, 903), (2, 69935, 1127, 724), (2, 71062, 849, 819),
    (1, 71911, 2873, 269), (2, 74784, 453, 197), (2, 75237, 348, 173), (2, 75585, 474, 1021),
    (2, 76059, 1126, 374),
]  # fmt: skip
CHARS_PER_TOKEN_SEEN = 5.8
CAP = 0.80


def _body(n_pairs: int, sizes: list[int]) -> dict[str, Any]:
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "text", "text": "x" * sizes[0]}]}
    ]
    for i in range(1, n_pairs + 1):
        msgs.append({"role": "assistant", "content": [{"type": "text", "text": "a" * 40}]})
        text = "u" * sizes[i]
        msgs.append({"role": "user", "content": [{"type": "text", "text": text}]})
    msgs[-1]["content"][0]["cache_control"] = {"type": "ephemeral"}
    return {"model": MODEL, "max_tokens": 4096, "system": "work", "messages": msgs}


def test_a1s_whole_sequence_fits_under_its_reservation(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
) -> None:  # fmt: skip
    _sid, tok = _session(store, budget, gw, amount=CAP)
    prompts = [a + b + c for a, b, c, _ in A1]
    sizes = [int(prompts[0] * CHARS_PER_TOKEN_SEEN)] + [
        max(60, int((prompts[i] - prompts[i - 1]) * CHARS_PER_TOKEN_SEEN)) for i in range(1, 25)
    ]
    rows, spent = [], 0.0
    print(f"\n{'#':>2} {'prompt':>7} {'task hold':>10} {'day/month':>10} {'actual':>8} {'cum':>7}")
    for i, (t_in, read, w5, out) in enumerate(A1):
        body = _body(i, sizes)
        upstream.count = prompts[i]  # only the first call is counted
        upstream.usage = {
            "input_tokens": t_in,
            "cache_read_input_tokens": read,
            "cache_creation": {"ephemeral_5m_input_tokens": w5},
        }
        upstream.usage_out = out
        gs = gw.authorize(tok)
        h = gw.preflight(gs, "/v1/messages", json.dumps(body).encode())
        gw.release(h)
        r = client.post("/v1/messages", content=json.dumps(body), headers={"x-api-key": tok})
        assert r.status_code == 200, (i + 1, r.text)
        actual = gw.prices.cost(
            MODEL,
            CallUsage(
                tokens_in=t_in, tokens_cache_read=read, tokens_cache_write_5m=w5, tokens_out=out
            ),
        )
        spent += actual
        rows.append((i + 1, prompts[i], h.amount, h.plain, actual, spent))
        print(
            f"{i + 1:>2} {prompts[i]:>7} {h.amount:>10.4f} {h.plain:>10.4f} {actual:>8.4f} {spent:>7.4f}"
        )
    print(f"max task hold {max(r[2] for r in rows):.4f}  max day/month hold "
          f"{max(r[3] for r in rows):.4f}  total {spent:.4f} of {CAP:.2f}")  # fmt: skip
    assert spent < CAP
    assert max(r[2] for r in rows[2:]) < 0.10  # past the two write-only calls, none ten cents
    # every call's hold covered its real cost: no overshoot, no page
    assert all(r[2] >= r[4] - 1e-9 for r in rows[1:])
    assert not [e for e in store.events() if e.type == "settle_excess"]

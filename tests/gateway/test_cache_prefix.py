"""#79 (a): a session's cached prefix is priced at the cache-read rate in the worst case.

The previous call of the same session wrote the prefix (the provider's usage said so),
this call resends it byte for byte (compared by hash, `cache_control` markers ignored)
within 50 minutes. The new tail stays at the 1-hour write rate. A cache miss settles
its real cost, records `settle_excess` (`cache_miss`), trips no breaker, and the
session's next call must re-reserve first.
"""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
import math
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from tests.gateway.test_gateway import PA, _session, budget, client, gw  # noqa: F401
from vigild.breakers import GLOBAL, Breakers, Kind
from vigild.budget import Budget
from vigild.config import Config
from vigild.db import Store
from vigild.gateway.service import CHARS_PER_TOKEN, Gateway, worst_case_usd
from vigild.metering.calls import CallUsage

MODEL = "claude-sonnet-5-5"
BIG = "x" * 30_000
TAIL = "y" * 3_000
MIN = 60.0


class Upstream:
    """Answers every call with the usage the test set."""

    def __init__(self) -> None:
        self.usage: dict[str, Any] = {}
        self.requests: list[httpx2.Request] = []

    def __call__(self, req: httpx2.Request) -> httpx2.Response:
        self.requests.append(req)
        return httpx2.Response(
            200,
            json={
                "model": MODEL,
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"output_tokens": 50, **self.usage},
            },
        )


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def clock(gw: Gateway) -> list[float]:
    t = [1000.0]
    gw._now = lambda: t[0]  # type: ignore[method-assign]
    return t


def _first() -> dict[str, Any]:
    return {
        "model": MODEL,
        "max_tokens": 4096,
        "system": "be brief",
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": BIG, "cache_control": {"type": "ephemeral"}}],
            }
        ],
    }


def _second(first_text: str = BIG) -> dict[str, Any]:
    """The first call's messages (its cache marker moved on, as Claude Code does), the
    model's answer, and a new tail."""
    return {
        "model": MODEL,
        "max_tokens": 4096,
        "system": "be brief",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": first_text}]},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            {
                "role": "user",
                "content": [{"type": "text", "text": TAIL, "cache_control": {"type": "ephemeral"}}],
            },
        ],
    }


def _post(client: TestClient, tok: str, body: dict[str, Any]) -> httpx2.Response:
    return client.post("/v1/messages", content=json.dumps(body), headers={"x-api-key": tok})


def _wrote(up: Upstream, n: int = 20_000) -> None:
    up.usage = {"input_tokens": 5, "cache_creation": {"ephemeral_1h_input_tokens": n}}


def _hold(gw: Gateway, tok: str, body: dict[str, Any]) -> tuple[float, int]:
    raw = json.dumps(body).encode()
    h = gw.preflight(gw.authorize(tok), "/v1/messages", raw)
    gw.release(h)
    return h.amount, len(raw)


def _canon_chars(body: dict[str, Any], n: int) -> int:
    """The prefix as the test sees it: tools, system and the first n messages, compact
    JSON, no cache markers."""

    def strip(x: Any) -> Any:
        if isinstance(x, dict):
            return {k: strip(v) for k, v in x.items() if k != "cache_control"}
        return [strip(v) for v in x] if isinstance(x, list) else x

    prefix = [strip(body.get("tools")), strip(body.get("system")), strip(body["messages"][:n])]
    return len(json.dumps(prefix, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _plain(gw: Gateway, raw_len: int) -> float:
    return worst_case_usd(gw.prices, MODEL, raw_len, 4096)


def test_a_resent_prefix_is_priced_at_the_cache_read_rate(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    _sid, tok = _session(store, budget, gw)
    _wrote(upstream)
    assert _post(client, tok, _first()).status_code == 200
    clock[0] += 10 * MIN
    second = _second()
    amount, raw_len = _hold(gw, tok, second)
    est_in = math.ceil(raw_len / CHARS_PER_TOKEN)
    prefix = math.ceil(_canon_chars(_first(), 1) / CHARS_PER_TOKEN)
    expect = gw.prices.cost(
        MODEL,
        CallUsage(tokens_cache_read=prefix, tokens_cache_write_1h=est_in - prefix, tokens_out=4096),
    )
    assert amount == pytest.approx(expect)
    assert amount < _plain(gw, raw_len)


def test_the_cache_rate_is_only_for_what_the_provider_said_it_wrote(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """The request's own markers say nothing: the previous response's usage does."""
    _sid, tok = _session(store, budget, gw)
    upstream.usage = {"input_tokens": 12_000}  # nothing cached
    assert _post(client, tok, _first()).status_code == 200
    amount, raw_len = _hold(gw, tok, _second())
    assert amount == pytest.approx(_plain(gw, raw_len))


def test_a_prefix_older_than_fifty_minutes_is_priced_as_before(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    _sid, tok = _session(store, budget, gw)
    _wrote(upstream)
    assert _post(client, tok, _first()).status_code == 200
    clock[0] += 49 * MIN
    assert _hold(gw, tok, _second())[0] < _plain(gw, len(json.dumps(_second())))
    clock[0] += 2 * MIN  # 51 minutes
    amount, raw_len = _hold(gw, tok, _second())
    assert amount == pytest.approx(_plain(gw, raw_len))


def test_a_changed_earlier_message_is_priced_as_before(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    _sid, tok = _session(store, budget, gw)
    _wrote(upstream)
    assert _post(client, tok, _first()).status_code == 200
    amount, raw_len = _hold(gw, tok, _second("z" + BIG[1:]))
    assert amount == pytest.approx(_plain(gw, raw_len))


def test_another_sessions_prefix_is_no_help(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    _a, tok_a = _session(store, budget, gw)
    _b, tok_b = _session(store, budget, gw)
    _wrote(upstream)
    assert _post(client, tok_a, _first()).status_code == 200
    amount, raw_len = _hold(gw, tok_b, _second())
    assert amount == pytest.approx(_plain(gw, raw_len))


def _miss(client: TestClient, gw: Gateway, tok: str, up: Upstream, clock: list[float]) -> None:
    _wrote(up)
    assert _post(client, tok, _first()).status_code == 200
    clock[0] += 10 * MIN
    # the provider did not have the prefix: it wrote everything again
    up.usage = {"input_tokens": 5, "cache_creation": {"ephemeral_1h_input_tokens": 14_000}}
    assert _post(client, tok, _second()).status_code == 200


def test_a_cache_miss_settles_its_real_cost_and_the_next_call_re_reserves(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    cfg: Config, clock: list[float],
) -> None:  # fmt: skip
    gw.breakers = Breakers(store, cfg)
    sid, tok = _session(store, budget, gw)
    _miss(client, gw, tok, upstream, clock)
    rows = store.q("SELECT cost_usd FROM model_calls WHERE session_id=? ORDER BY id", (sid,))
    real = sum(float(r["cost_usd"]) for r in rows)
    (ev,) = [e for e in store.events() if e.type == "settle_excess"]
    assert ev.data["reason"] == "cache_miss"
    assert ev.data["excess_usd"] > 0
    assert ev.data["reported_usd"] == pytest.approx(
        float(rows[1]["cost_usd"]), abs=1e-6
    ) and ev.data["reported_usd"] == pytest.approx(
        ev.data["reserved_usd"] + ev.data["excess_usd"], abs=1e-5
    )
    assert not gw.breakers.is_open(Kind.DAILY, GLOBAL)
    assert budget.settle_session(sid) == pytest.approx(real)  # the real cost, not the hold
    assert real > 0


def test_after_a_miss_the_next_call_is_refused_until_it_re_reserves(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    sid, tok = _session(store, budget, gw)
    _miss(client, gw, tok, upstream, clock)
    (ev,) = [e for e in store.events() if e.type == "settle_excess"]
    excess = ev.data["excess_usd"]
    open_before = budget.open_today()
    # the day has no room for the re-reservation: the normal budget refusal
    budget.cfg.daily_usd = budget.spent_today() + open_before
    r = _post(client, tok, _first())
    assert r.status_code == 403 and "budget" in r.json()["error"]["message"]
    assert budget.open_today() == pytest.approx(open_before)
    # room again: the call re-reserves the excess first, then goes through
    budget.cfg.daily_usd = 5.0
    assert _post(client, tok, _first()).status_code == 200
    (extra,) = store.q(
        "SELECT amount_usd FROM reservations WHERE session_id=? AND purpose=?",
        (sid, "cache_miss_rereserve"),
    )
    assert float(extra["amount_usd"]) == pytest.approx(excess, abs=1e-5)
    assert _post(client, tok, _first()).status_code == 200  # once, not on every call
    assert len(store.q("SELECT 1 FROM reservations WHERE purpose='cache_miss_rereserve'")) == 1


def test_any_other_settle_excess_still_trips_the_daily_breaker(
    gw: Gateway, store: Store, cfg: Config
) -> None:
    gw.breakers = Breakers(store, cfg)
    payload = {"result": {"usage": {"input_tokens": 10_000_000, "output_tokens": 0}}}
    gw.metered(repo=PA, route="jev-openrouter", provider="openrouter", model="typesafe/jev-1.13",
               purpose="decider", job_id=None, run=lambda: payload, private=False,
               body_chars=30)  # fmt: skip
    assert gw.breakers.is_open(Kind.DAILY, GLOBAL)
    (ev,) = [e for e in store.events() if e.type == "settle_excess"]
    assert "reason" not in ev.data

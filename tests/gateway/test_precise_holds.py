"""Precise holds (owner ruling R23, 2026-10-31 (#1)): the A1 floor blocker.

A prefix that hash-matches the session's previous call is counted from that call's
reported usage (reads at the read rate, the rest at the 1-hour write rate) plus an
estimated tail; a first or changed prefix is counted exactly by the provider
(`count_tokens`, llama-server `/tokenize`); the day and the month always see the
all-miss price, so they stay hard; a call that costs more than its hold pages the
owner and makes the rest of its task all-miss.

Every expected dollar below is computed from the price table.
"""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import asyncio
import json
import math
import threading
import time
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from tests.gateway.test_gateway import PA, _session, budget, client, gw  # noqa: F401
from vigild.budget import Budget
from vigild.config import Config
from vigild.db import Store
from vigild.gateway.service import CHARS_PER_TOKEN, Gateway, GatewayError, prefix_shape
from vigild.jobs.model import Role
from vigild.metering.calls import CallUsage

MODEL = "claude-sonnet-5-5"
MIN = 60.0
OUT = 4096


class Upstream:
    """Answers /v1/messages with the usage the test set, and the counting routes with
    what the test set. Records every request."""

    def __init__(self) -> None:
        self.usage: dict[str, Any] = {}
        self.requests: list[httpx2.Request] = []
        self.count = 1000  # count_tokens' answer
        self.count_status = 200
        self.count_raises: Exception | None = None
        self.tokens = 1000  # /tokenize's answer: this many tokens
        self.usage_out = 50
        self.count_delay = 0.0  # seconds the counter takes
        self.msg_status = 200
        self.msg_raises: Exception | None = None
        self.stream = False

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def __call__(self, req: httpx2.Request) -> httpx2.Response:
        self.requests.append(req)
        if req.url.path.endswith("/count_tokens"):
            if self.count_delay:
                time.sleep(self.count_delay)
            if self.count_raises is not None:
                raise self.count_raises
            if self.count_status != 200:
                return httpx2.Response(self.count_status, json={"type": "error"})
            return httpx2.Response(200, json={"input_tokens": self.count})
        if req.url.path.endswith("/tokenize"):
            return httpx2.Response(200, json={"tokens": list(range(self.tokens))})
        if self.msg_raises is not None:
            raise self.msg_raises
        if self.msg_status != 200:
            return httpx2.Response(self.msg_status, json={"type": "error"})
        if self.stream:
            events = [
                {"type": "message_start", "message": {"model": MODEL, "usage": self.usage}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                 "usage": {"output_tokens": self.usage_out}},
                {"type": "message_stop"},
            ]  # fmt: skip
            data = b"".join(
                f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events
            )
            return httpx2.Response(200, content=data, headers={"content-type": "text/event-stream"})
        return httpx2.Response(
            200,
            json={
                "model": MODEL,
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"output_tokens": self.usage_out, **self.usage},
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


def _first(n: int = 30_000) -> dict[str, Any]:
    return {
        "model": MODEL,
        "max_tokens": OUT,
        "system": "be brief",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "x" * n, "cache_control": {"type": "ephemeral"}}
                ],
            }
        ],
    }


def _second(n: int = 30_000, tail: int = 4_500) -> dict[str, Any]:
    """The first call's messages, the model's answer, and a new tail."""
    return {
        "model": MODEL,
        "max_tokens": OUT,
        "system": "be brief",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "x" * n}]},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "y" * tail, "cache_control": {"type": "ephemeral"}}
                ],
            },
        ],
    }


def _post(client: TestClient, tok: str, body: dict[str, Any]) -> httpx2.Response:
    return client.post("/v1/messages", content=json.dumps(body), headers={"x-api-key": tok})


def _tail_tokens(first: dict[str, Any], second: dict[str, Any]) -> int:
    """The bytes the second request appended to the first, as the gateway estimates them."""
    a = prefix_shape(first).chars
    b = prefix_shape(second).chars
    return math.ceil((b - a) / CHARS_PER_TOKEN)


def _pre(gw: Gateway, tok: str, body: dict[str, Any], *, keep: bool = False) -> Any:
    h = gw.preflight(gw.authorize(tok), "/v1/messages", json.dumps(body).encode())
    if not keep:
        gw.release(h)
    return h


def _usd(gw: Gateway, **kw: int) -> float:
    return gw.prices.cost(MODEL, CallUsage(**kw))


def _reads(up: Upstream, n: int, tokens_in: int = 5) -> int:
    """The provider reports n cache reads; returns the prompt total it reported."""
    up.usage = {"input_tokens": tokens_in, "cache_read_input_tokens": n}
    return tokens_in + n


def _sess(store: Store, budget: Budget, gw: Gateway, amount: float) -> tuple[str, str]:
    return _session(store, budget, gw, amount=amount)


# --- (a) A1's refused call -------------------------------------------------------------


def test_a1s_refused_call_is_admitted_and_its_input_hold_is_a_cent_or_two(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """s-a3ccbbac44, 19:03:11 UTC: nothing in flight, the previous call reported
    2 / 76,059 / 1,126 (5m) = 77,187 prompt tokens, $0.328 left. The old `chars / 3`
    read the request as about 149k tokens and held about $0.30 of phantom writes."""
    n_first = 440_000
    upstream.usage = {
        "input_tokens": 2,
        "cache_read_input_tokens": 76_059,
        "cache_creation": {"ephemeral_5m_input_tokens": 1_126},
    }
    first_cost = _usd(
        gw, tokens_in=2, tokens_cache_read=76_059, tokens_cache_write_5m=1_126, tokens_out=50
    )
    upstream.count = 77_000  # the first call's exact count
    _sid, tok = _sess(store, budget, gw, first_cost + 0.328)
    assert _post(client, tok, _first(n_first)).status_code == 200
    clock[0] += 2 * MIN
    second = _second(n_first, 4_500)
    tail = _tail_tokens(_first(n_first), second)
    # owner, 2026-11-01: the 1,126 the previous call wrote are cached too, at the read rate
    expect_in = _usd(gw, tokens_cache_read=76_059 + 1_126, tokens_cache_write_5m=2 + tail)
    h = _pre(gw, tok, second, keep=True)
    try:
        assert h.amount == pytest.approx(expect_in + _usd(gw, tokens_out=OUT))
        assert h.amount - _usd(gw, tokens_out=OUT) == pytest.approx(0.011, abs=0.002)
    finally:
        gw.release(h)
    assert _post(client, tok, second).status_code == 200  # admitted


# --- (b) a forced miss ---------------------------------------------------------------


def _miss_setup(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, up: Upstream,
    clock: list[float], reads: int = 60_000,
) -> tuple[str, str, int, float]:  # fmt: skip
    """A session whose second call is held as a hit and then misses. The reservation is
    just enough for the first call and the precise hold, so a miss runs it past its hold.
    Returns the session, its token, the prompt tokens of the first call and the second
    call's miss premium."""
    total = _reads(up, reads)
    first_cost = _usd(gw, tokens_in=5, tokens_cache_read=reads, tokens_out=50)
    tail = _tail_tokens(_first(), _second())
    hold = _usd(gw, tokens_cache_read=reads, tokens_cache_write_5m=5 + tail, tokens_out=OUT)
    premium = _usd(gw, tokens_cache_write_5m=reads + 5 + tail) - _usd(
        gw, tokens_cache_read=reads, tokens_cache_write_5m=5 + tail
    )
    sid, tok = _sess(store, budget, gw, first_cost + hold + 0.001)
    assert _post(client, tok, _first()).status_code == 200
    clock[0] += 4 * MIN
    # the provider did not have the prefix: it wrote all of it again
    up.usage = {
        "input_tokens": 5,
        "cache_creation": {"ephemeral_5m_input_tokens": reads + tail},
    }
    assert _post(client, tok, _second()).status_code == 200
    return sid, tok, total, premium


def test_a_forced_miss_overshoots_by_at_most_its_premium_pages_and_holds_the_task_as_a_miss(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    sid, tok, _total, premium = _miss_setup(client, gw, store, budget, upstream, clock)
    (ev,) = [e for e in store.events() if e.type == "settle_excess"]
    assert ev.data["reason"] == "cache_miss"
    assert 0 < ev.data["excess_usd"] <= premium + 1e-9
    assert ev.data["actual_usd"] == pytest.approx(ev.data["reserved_usd"] + ev.data["excess_usd"])
    (page,) = [i for i in store.list_inbox() if i.kind == "page"]
    assert "overshoot" in page.title
    for k in ("task_id", "hold_usd", "actual_usd", "excess_usd"):
        assert k in page.body
    # the next call on the task is held as a full miss: all of the prompt at the write rate
    # (the excess is re-reserved first, from the day, which has room)
    budget.reserve(session_id=sid, task_id=None, amount=1.0, purpose="room for a full miss")
    second = _second()
    prompt = 60_000 + _tail_tokens(_first(), second)
    tail = _tail_tokens(second, {**second, "messages": [*second["messages"], *second["messages"]]})
    del tail
    h = _pre(gw, tok, second, keep=True)
    try:
        assert h.premium == 0
        assert h.cached_tokens == 0
        assert h.amount >= _usd(gw, tokens_cache_write_5m=prompt, tokens_out=OUT) - 1e-9
    finally:
        gw.release(h)


# --- (c) the day and the month stay hard ---------------------------------------------


def _two_sessions_on_hits(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, up: Upstream,
    clock: list[float], reads: int = 60_000,
) -> tuple[str, str, float]:  # fmt: skip
    """Two sessions whose next call is held as a hit. Returns their tokens and one
    all-miss call's price."""
    _reads(up, reads)
    toks = []
    for _ in range(2):
        _sid, tok = _sess(store, budget, gw, 1.0)
        assert _post(client, tok, _first()).status_code == 200
        toks.append(tok)
    clock[0] += 4 * MIN
    tail = _tail_tokens(_first(), _second())
    all_miss = _usd(gw, tokens_cache_write_5m=reads + 5 + tail, tokens_out=OUT)
    return toks[0], toks[1], all_miss


@pytest.mark.parametrize("cap", ["daily", "monthly"])
def test_day_and_month_cannot_be_exceeded_even_if_every_concurrent_call_misses(
    cap: str, client: TestClient, gw: Gateway, store: Store, budget: Budget,
    upstream: Upstream, clock: list[float],
) -> None:  # fmt: skip
    a, b, all_miss = _two_sessions_on_hits(client, gw, store, budget, upstream, clock)
    used_day = budget.spent_today() + budget.open_today()
    used_month = budget.spent_month() + budget.open_month()
    budget.cfg.daily_usd = used_day + all_miss * 1.01 if cap == "daily" else 1_000.0
    budget.cfg.monthly_usd = used_month + all_miss * 1.01 if cap == "monthly" else 1_000.0
    first = _pre(gw, a, _second(), keep=True)
    try:
        assert first.amount < all_miss  # the task hold is the cheap one
        with pytest.raises(GatewayError) as e:
            _pre(gw, b, _second())
        assert e.value.status == 403 and cap in e.value.body()["error"]["message"]
        # the refused call left nothing held, and the first call's premium goes back on release
        assert budget.premium_total() == pytest.approx(first.premium)
    finally:
        gw.release(first)
    assert budget.premium_total() == 0
    gw.release(_pre(gw, b, _second(), keep=True))  # now there is room
    # the open premium is a reservation too: no new session can take what it holds
    hold = _pre(gw, a, _second(), keep=True)
    try:
        room = budget.cfg.daily_usd - budget.spent_today() - budget.open_today()
        from vigild.budget import BudgetExceeded

        if cap == "daily":
            with pytest.raises(BudgetExceeded):
                budget.reserve(
                    session_id=None, task_id=None, amount=room - hold.premium + 0.01, purpose="x"
                )
    finally:
        gw.release(hold)


# --- (d) (e) the exact count of a first call -------------------------------------------


def test_a_first_call_is_held_from_count_tokens_not_a_third_of_its_bytes(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
) -> None:  # fmt: skip
    upstream.count = 7_000
    _sid, tok = _sess(store, budget, gw, 1.0)
    body = _first(60_000)  # chars / 3 would read 20k tokens
    h = _pre(gw, tok, body)
    assert h.amount == pytest.approx(_usd(gw, tokens_cache_write_5m=7_000, tokens_out=OUT))
    assert h.premium == 0
    (req,) = [r for r in upstream.requests if r.url.path.endswith("/count_tokens")]
    sent = json.loads(req.content)
    assert sent["model"] == MODEL and sent["messages"] == body["messages"]
    assert "max_tokens" not in sent
    assert req.headers["x-api-key"] and not [e for e in store.events() if "fallback" in e.type]


@pytest.mark.parametrize("how", ["error", "timeout", "garbage"])
def test_a_failed_count_falls_back_to_a_third_of_the_bytes_and_logs_it(
    how: str, client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
) -> None:  # fmt: skip
    if how == "error":
        upstream.count_status = 500
    elif how == "timeout":
        upstream.count_raises = httpx2.ReadTimeout("slow")
    else:
        upstream.count = 0  # not a count
    _sid, tok = _sess(store, budget, gw, 1.0)
    body = _first(60_000)
    h = _pre(gw, tok, body)
    raw_len = len(json.dumps(body).encode())
    assert h.amount == pytest.approx(
        _usd(gw, tokens_cache_write_5m=math.ceil(raw_len / CHARS_PER_TOKEN), tokens_out=OUT)
    )
    (ev,) = [e for e in store.events() if e.type == "hold_estimate_fallback"]
    assert ev.data["preset"] == "claude-sonnet" and ev.data["reason"]
    assert set(ev.data) == {"preset", "reason"}  # no body, no text
    assert "x" * 100 not in json.dumps(ev.data)


def test_a_slow_count_is_cut_off_by_a_short_timeout(gw: Gateway) -> None:
    from vigild.gateway import service

    assert 0 < service.COUNT_TIMEOUT_S <= 5


# --- the tower and OpenRouter -----------------------------------------------------------


def test_a_local_presets_first_call_is_counted_by_tokenize(
    gw: Gateway, store: Store, budget: Budget, cfg: Config, upstream: Upstream,
) -> None:  # fmt: skip
    cfg.repos.repos[PA].backends.append("tower-qwen")
    s = store.create_session(None, Role.WORKER, backend_preset="tower-qwen")
    budget.reserve(session_id=s.id, task_id=f"t-{s.id}", amount=1.0, purpose="worker")
    tok = gw.issue_token(s.id, PA, "tower-qwen")
    body = {**_first(3_000), "model": "qwen3.6-35b-a3b"}
    gw.release(_pre(gw, tok, body))
    (req,) = [r for r in upstream.requests if r.url.path.endswith("/tokenize")]
    assert str(req.url) == "http://tower:8080/tokenize"  # the base_url's /v1 is not doubled
    assert req.headers["authorization"].startswith("Bearer ")
    assert "content" in json.loads(req.content)
    assert not [r for r in upstream.requests if r.url.path.endswith("/count_tokens")]


def test_openrouter_has_no_count_endpoint_so_it_is_a_third_of_the_bytes(
    gw: Gateway, store: Store, cfg: Config, upstream: Upstream,
) -> None:  # fmt: skip
    from vigild.gateway.service import GatewaySession

    gs = GatewaySession("s-x", PA, "openrouter", None, None, model=MODEL)
    assert gw._count_input(gs, cfg.preset("openrouter"), _first(), {}) is None
    assert upstream.requests == []
    (ev,) = [e for e in store.events() if e.type == "hold_estimate_fallback"]
    assert ev.data == {"preset": "openrouter", "reason": "no_count_endpoint"}


# --- the guards kept from #215 ------------------------------------------------------------


def test_a_call_in_flight_does_not_make_the_next_a_miss(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """Owner, 2026-11-01 (vi-0019 A1, step a): the prefix the last *completed* call reported
    is held at the read rate whether or not another call of the session is in flight; what
    the call in flight is still writing is in the tail, at the write rate."""
    reads = 20_000
    _reads(upstream, reads)
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200
    upstream.count = 25_000
    a = _pre(gw, tok, _second(), keep=True)
    b = _pre(gw, tok, _second(), keep=True)  # the first is still in flight
    try:
        tail = _tail_tokens(_first(), _second())
        expect = _usd(gw, tokens_cache_read=reads, tokens_cache_write_5m=5 + tail, tokens_out=OUT)
        assert a.amount == pytest.approx(expect)
        assert b.amount == pytest.approx(expect)
        assert b.cached_tokens == reads and b.premium > 0
        assert "/v1/messages/count_tokens" not in upstream.paths()[1:]  # a match is never counted
    finally:
        gw.release(a)
        gw.release(b)


def test_a_cache_write_earns_the_read_rate_on_the_next_call(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """Owner, 2026-11-01 (vi-0019 A1, step a): tokens the previous completed call reported
    as cached, reads and writes alike, are held at the read rate on the next call; a miss
    goes through the overshoot path."""
    upstream.usage = {"input_tokens": 5, "cache_creation": {"ephemeral_5m_input_tokens": 20_000}}
    upstream.count = 20_005  # the first call's exact count, so it is no overshoot
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200
    tail = _tail_tokens(_first(), _second())
    h = _pre(gw, tok, _second())
    assert h.cached_tokens == 20_000
    assert h.amount == pytest.approx(
        _usd(gw, tokens_cache_read=20_000, tokens_cache_write_5m=5 + tail, tokens_out=OUT)
    )
    assert h.premium > 0


def test_a_prefixs_validity_follows_the_ttl_of_the_write_that_made_it(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """Owner, 2026-11-01 (follow-up to #256): a cached prefix is valid for the TTL its
    write asked for (5m: 5 minutes; 1h: 60 minutes, capped by the 50-minute ceiling), not
    the TTL the next request asks for."""
    _reads(upstream, 20_000)
    upstream.count = 9_999
    miss = _usd(gw, tokens_cache_write_5m=9_999, tokens_out=OUT)
    miss_1h = _usd(gw, tokens_cache_write_1h=9_999, tokens_out=OUT)
    # a 1h write: valid for 50 minutes, whatever the next request asks for
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _with_ttl(_first(), "1h")).status_code == 200
    clock[0] += 6 * MIN
    assert _pre(gw, tok, _second()).premium > 0  # a 5m request at 6 minutes: still a hit
    one_h = _with_ttl(_second(), "1h")
    clock[0] += 43 * MIN  # 49 minutes
    assert _pre(gw, tok, one_h).premium > 0
    clock[0] += 2 * MIN  # 51 minutes
    h = _pre(gw, tok, one_h)
    assert h.amount == pytest.approx(miss_1h) and h.premium == 0
    # a 5m write: valid for 5 minutes
    _sid2, tok2 = _sess(store, budget, gw, 1.0)
    assert _post(client, tok2, _first()).status_code == 200
    clock[0] += 4 * MIN
    assert _pre(gw, tok2, _second()).premium > 0  # a hit after 4 minutes
    clock[0] += 2 * MIN  # 6 minutes
    h = _pre(gw, tok2, _second())
    assert h.amount == pytest.approx(miss) and h.premium == 0


def test_a_5m_write_then_a_1h_request_is_a_hit_for_at_most_five_minutes(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """The case the #256 reviews flagged: the previous call wrote at 5m, the next asks for
    1h. The provider's entry expired at 5 minutes, so at 6 minutes the call is counted
    again at the 1h write rate, not priced as a hit."""
    _reads(upstream, 20_000)
    upstream.count = 9_999
    miss_1h = _usd(gw, tokens_cache_write_1h=9_999, tokens_out=OUT)
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200  # a 5m write
    one_h = _with_ttl(_second(), "1h")
    clock[0] += 4 * MIN
    assert _pre(gw, tok, one_h).premium > 0  # within 5 minutes: a hit
    clock[0] += 2 * MIN  # 6 minutes
    h = _pre(gw, tok, one_h)
    assert h.amount == pytest.approx(miss_1h) and h.premium == 0 and h.reason == "count"


def test_a_changed_model_or_thinking_is_counted_again(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    _reads(upstream, 20_000)
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200
    upstream.count = 8_888
    thinking = {
        **_second(),
        "max_tokens": 8192,
        "thinking": {"type": "enabled", "budget_tokens": 2000},
    }
    h = _pre(gw, tok, thinking)
    assert h.amount == pytest.approx(_usd(gw, tokens_cache_write_5m=8_888, tokens_out=8192))
    assert h.cached_tokens == 0


# --- the write rate follows the TTL the request asks for --------------------------------


def _with_ttl(body: dict[str, Any], ttl: str | None, where: str = "messages") -> dict[str, Any]:
    marker: dict[str, Any] = {"type": "ephemeral"}
    if ttl:
        marker["ttl"] = ttl
    body = json.loads(json.dumps(body))
    if where == "system":
        body["system"] = [{"type": "text", "text": "be brief", "cache_control": marker}]
    else:
        body["messages"][-1]["content"][-1]["cache_control"] = marker
    return body


@pytest.mark.parametrize(
    ("ttl", "where", "kind"),
    [(None, "messages", "5m"), ("5m", "messages", "5m"), ("1h", "messages", "1h"),
     ("1h", "system", "1h")],
)  # fmt: skip
def test_cache_writes_are_held_at_the_rate_of_the_ttl_the_request_asks_for(
    ttl: str | None, where: str, kind: str, gw: Gateway, store: Store, budget: Budget,
    upstream: Upstream,
) -> None:  # fmt: skip
    upstream.count = 7_000
    _sid, tok = _sess(store, budget, gw, 1.0)
    h = _pre(gw, tok, _with_ttl(_first(6_000), ttl, where))
    other = "1h" if kind == "5m" else "5m"
    assert h.amount == pytest.approx(
        _usd(gw, **{f"tokens_cache_write_{kind}": 7_000}, tokens_out=OUT)
    )
    assert h.amount != pytest.approx(
        _usd(gw, **{f"tokens_cache_write_{other}": 7_000}, tokens_out=OUT)
    )


def test_a_hit_with_a_1h_breakpoint_prices_its_writes_and_premium_at_1h(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    reads = 20_000
    _reads(upstream, reads)
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200
    tail = _tail_tokens(_first(), _second())
    # a 1h marker on the tail only: the prefix hash ignores markers
    h = _pre(gw, tok, _with_ttl(_second(), "1h"))
    assert h.amount == pytest.approx(
        _usd(gw, tokens_cache_read=reads, tokens_cache_write_1h=5 + tail, tokens_out=OUT)
    )
    all_miss = _usd(gw, tokens_cache_write_1h=reads + 5 + tail, tokens_out=OUT)
    assert h.premium == pytest.approx(all_miss - h.amount)


def test_a_changed_earlier_message_or_another_session_is_counted_not_a_hit(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    _reads(upstream, 20_000)
    _a, tok_a = _sess(store, budget, gw, 1.0)
    _b, tok_b = _sess(store, budget, gw, 1.0)
    assert _post(client, tok_a, _first()).status_code == 200
    upstream.count = 6_666
    changed = _second()
    changed["messages"][0]["content"][0]["text"] = (
        "z" + changed["messages"][0]["content"][0]["text"][1:]
    )
    for tok, body in ((tok_a, changed), (tok_b, _second())):
        h = _pre(gw, tok, body)
        assert h.amount == pytest.approx(_usd(gw, tokens_cache_write_5m=6_666, tokens_out=OUT))
        assert h.cached_tokens == 0 and h.premium == 0


def test_a_failed_metering_books_the_all_miss_price(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    reads = 20_000
    _reads(upstream, reads)
    sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200
    tail = _tail_tokens(_first(), _second())

    def boom(**kw: Any) -> float:
        raise RuntimeError("db down")

    gw._record = boom  # type: ignore[method-assign]
    assert _post(client, tok, _second()).status_code == 200
    (row,) = store.q(
        "SELECT amount_usd FROM ledger WHERE session_id=? AND reservation_id IS NULL", (sid,)
    )
    assert float(row["amount_usd"]) == pytest.approx(
        _usd(gw, tokens_cache_write_5m=reads + 5 + tail, tokens_out=OUT)
    )


def test_a_low_count_that_overshoots_its_hold_pages_and_holds_the_task_as_a_miss(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """Rule 5 is for any call that costs more than its task hold, not only a cache-priced one."""
    upstream.count = 1_000  # the provider's count under-reports
    upstream.usage = {
        "input_tokens": 5,
        "cache_read_input_tokens": 20_000,
        "cache_creation": {"ephemeral_5m_input_tokens": 40_000},
    }
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200
    (ev,) = [e for e in store.events() if e.type == "settle_excess"]
    assert ev.data["reason"] == "estimate_low" and ev.data["excess_usd"] > 0
    (page,) = [i for i in store.list_inbox() if i.kind == "page"]
    assert "overshoot" in page.title
    clock[0] += MIN
    tail = _tail_tokens(_first(), _second())
    h = _pre(gw, tok, _second())
    assert h.premium == 0 and h.cached_tokens == 0
    assert h.amount == pytest.approx(
        _usd(gw, tokens_cache_write_5m=60_005 + tail, tokens_out=OUT), rel=1e-6
    )


# --- fix round (review of #251) -----------------------------------------------------------


def _primed(
    client: TestClient, store: Store, budget: Budget, gw: Gateway, up: Upstream,
    clock: list[float], reads: int = 20_000,
) -> tuple[str, str]:  # fmt: skip
    """A session whose next call is held as a hit (so it carries a premium)."""
    _reads(up, reads)
    sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200
    clock[0] += MIN
    return sid, tok


def test_a_cancelled_request_releases_its_hold_and_its_premium(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    sid, tok = _primed(client, store, budget, gw, upstream, clock)
    gate = threading.Event()
    placed = threading.Event()
    real = gw._backend_gate

    def slow_gate(preset_name: str, session_id: str | None = None) -> str | None:
        placed.set()  # the hold and the premium are placed by now
        gate.wait(5)
        return real(preset_name, session_id)

    monkeypatch.setattr(gw, "_backend_gate", slow_gate)

    async def run() -> None:
        gs = gw.authorize(tok)
        raw = json.dumps(_second()).encode()
        task = asyncio.create_task(gw.forward(gs, "/v1/messages", {}, raw))
        while not placed.is_set():
            await asyncio.sleep(0.01)
        assert budget.premium_total() > 0 and sid in gw._inflight
        task.cancel()  # the client went away
        with pytest.raises(asyncio.CancelledError):
            await task
        gate.set()
        for _ in range(100):
            if sid not in gw._inflight and budget.premium_total() == 0:
                break
            await asyncio.sleep(0.02)

    asyncio.run(run())
    assert sid not in gw._inflight and budget.premium_total() == 0


def test_a_cjk_or_base64_tail_is_held_at_its_bytes_over_three(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """The tail is estimated in UTF-8 bytes, not characters: three-byte CJK and four-byte
    emoji are about a token each, and both the task hold and the day/month figure see it."""
    reads = 20_000
    for tail_text in ("漢" * 3_000, "😀" * 2_000, "QUJD" * 2_500):
        _sid, tok = _primed(client, store, budget, gw, upstream, clock, reads)
        body = _second()
        body["messages"][-1]["content"][-1]["text"] = tail_text
        nbytes = len(tail_text.encode())
        h = _pre(gw, tok, body)
        floor = math.ceil(nbytes / CHARS_PER_TOKEN)
        assert (
            h.amount
            >= _usd(gw, tokens_cache_read=reads, tokens_cache_write_5m=5 + floor, tokens_out=OUT)
            - 1e-9
        )
        assert h.plain >= _usd(gw, tokens_cache_write_5m=reads + 5 + floor, tokens_out=OUT) - 1e-9


def test_an_overshoot_reserves_its_excess_at_once_so_the_day_never_drops(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    sid, tok = _sess(store, budget, gw, 1.0)[0], None
    _reads(upstream, 60_000)
    tok = gw.issue_token(sid, PA, "claude-sonnet")
    assert _post(client, tok, _first()).status_code == 200
    clock[0] += MIN
    upstream.usage = {"input_tokens": 5, "cache_creation": {"ephemeral_5m_input_tokens": 61_500}}
    spent_before = budget.spent_today()
    assert _post(client, tok, _second()).status_code == 200
    (ev,) = [e for e in store.events() if e.type == "settle_excess"]
    excess = ev.data["excess_usd"]
    assert excess > 0
    # at once, in _learn: the day already holds the excess, no premium and no owed amount
    assert budget.premium_total() == 0 and sid not in gw._rereserve
    (extra,) = store.q(
        "SELECT amount_usd FROM reservations WHERE session_id=? AND purpose='cache_miss_rereserve'",
        (sid,),
    )
    assert float(extra["amount_usd"]) == pytest.approx(excess, abs=1e-5)
    assert budget.spent_today() == spent_before  # nothing settled yet
    # a second session cannot reserve into the excess
    budget.cfg.daily_usd = budget.spent_today() + budget.open_today() + excess * 0.5
    from vigild.budget import BudgetExceeded

    with pytest.raises(BudgetExceeded):
        budget.reserve(session_id=None, task_id=None, amount=excess * 0.9, purpose="other")


def test_two_calls_in_flight_at_once_cannot_both_take_the_last_of_the_day(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    a, b, all_miss = _two_sessions_on_hits(client, gw, store, budget, upstream, clock)
    budget.cfg.daily_usd = budget.spent_today() + budget.open_today() + all_miss * 1.01
    barrier = threading.Barrier(2)
    results: list[Any] = []

    def go(tok: str) -> None:
        barrier.wait()
        try:
            results.append(_pre(gw, tok, _second(), keep=True))
        except GatewayError as e:
            results.append(e)

    threads = [threading.Thread(target=go, args=(t,)) for t in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    admitted = [r for r in results if not isinstance(r, GatewayError)]
    assert len(admitted) == 1 and len(results) == 2
    assert budget.premium_total() == pytest.approx(admitted[0].premium)
    for h in admitted:
        gw.release(h)
    assert budget.premium_total() == 0


def test_an_upstream_error_releases_the_hold_and_the_premium(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    sid, tok = _primed(client, store, budget, gw, upstream, clock)
    upstream.msg_status = 529
    assert _post(client, tok, _second()).status_code == 529
    assert sid not in gw._inflight and budget.premium_total() == 0


def test_an_exception_on_the_wire_releases_the_hold_and_the_premium(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    sid, tok = _primed(client, store, budget, gw, upstream, clock)
    upstream.msg_raises = httpx2.ConnectError("down")

    async def run() -> None:
        with pytest.raises(httpx2.ConnectError):
            await gw.forward(gw.authorize(tok), "/v1/messages", {}, json.dumps(_second()).encode())

    asyncio.run(run())
    assert sid not in gw._inflight and budget.premium_total() == 0


def test_a_stream_aborted_midway_releases_the_hold_and_the_premium(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    sid, tok = _primed(client, store, budget, gw, upstream, clock)
    upstream.stream = True

    async def run() -> None:
        body = {**_second(), "stream": True}
        _status, _h, gen = await gw.forward(
            gw.authorize(tok), "/v1/messages", {}, json.dumps(body).encode()
        )
        assert budget.premium_total() > 0
        it = gen.__aiter__()  # type: ignore[union-attr]
        await it.__anext__()
        await it.aclose()  # type: ignore[attr-defined]  # the client went away

    asyncio.run(run())
    assert sid not in gw._inflight and budget.premium_total() == 0


def test_a_session_with_no_room_for_any_output_is_refused_before_it_is_counted(
    gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
) -> None:  # fmt: skip
    _sid, tok = _sess(store, budget, gw, 0.001)
    with pytest.raises(GatewayError):
        _pre(gw, tok, _first())
    assert not [p for p in upstream.paths() if p.endswith("count_tokens")]


def test_tool_choice_is_counted_with_the_request(
    gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
) -> None:  # fmt: skip
    _sid, tok = _sess(store, budget, gw, 1.0)
    tool = {"name": "t", "description": "d", "input_schema": {"type": "object"}}
    body = {**_first(3_000), "tools": [tool], "tool_choice": {"type": "tool", "name": "t"}}
    gw.release(_pre(gw, tok, body))
    (req,) = [r for r in upstream.requests if r.url.path.endswith("/count_tokens")]
    assert json.loads(req.content)["tool_choice"] == {"type": "tool", "name": "t"}


def test_the_count_has_one_total_deadline(
    gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from vigild.gateway import service

    monkeypatch.setattr(service, "COUNT_TIMEOUT_S", 0.2)
    upstream.count_delay = 1.5  # a counter that drips: no single phase times out
    _sid, tok = _sess(store, budget, gw, 1.0)
    t0 = time.monotonic()
    gw.release(_pre(gw, tok, _first(3_000)))
    assert time.monotonic() - t0 < 1.0
    (ev,) = [e for e in store.events() if e.type == "hold_estimate_fallback"]
    assert ev.data["reason"] == "timeout"


# --- a stream the client leaves before reading a byte -------------------------------------


async def _call_asgi(gw: Gateway, tok: str, body: dict[str, Any], *, disconnect: bool) -> None:
    """Drive the gateway app directly: the request, then (if `disconnect`) the client
    leaving before any response byte is read (`send` never completes)."""
    from vigild.gateway.app import create_gateway_app

    app = create_gateway_app(gw)
    payload = json.dumps(body).encode()
    sent_body = False
    stuck = asyncio.Event()
    got: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": payload, "more_body": False}
        if disconnect:
            await asyncio.sleep(0.2)
            return {"type": "http.disconnect"}
        await stuck.wait()
        return {"type": "http.disconnect"}

    async def send(msg: dict[str, Any]) -> None:
        got.append(msg)
        if disconnect:
            await stuck.wait()  # the client is gone: nothing is read

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "path": "/v1/messages", "raw_path": b"/v1/messages", "query_string": b"",
        "root_path": "", "scheme": "http", "server": ("test", 80), "client": ("c", 1),
        "headers": [(b"x-api-key", tok.encode()), (b"content-type", b"application/json")],
    }  # fmt: skip
    await asyncio.wait_for(app(scope, receive, send), 5)


def test_a_stream_the_client_leaves_before_reading_releases_its_hold_and_premium(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    sid, tok = _primed(client, store, budget, gw, upstream, clock)
    upstream.stream = True
    asyncio.run(_call_asgi(gw, tok, {**_second(), "stream": True}, disconnect=True))
    assert sid not in gw._inflight and budget.premium_total() == 0


def test_a_fully_read_stream_releases_exactly_once(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    sid, tok = _primed(client, store, budget, gw, upstream, clock)
    upstream.stream = True
    calls: list[float] = []
    real = budget.release_premium

    def counting(session_id: str, amount: float) -> None:
        calls.append(amount)
        real(session_id, amount)

    monkeypatch.setattr(budget, "release_premium", counting)
    rows_before = store.q("SELECT COUNT(*) n FROM model_calls")[0]["n"]
    r = client.post(
        "/v1/messages",
        content=json.dumps({**_second(), "stream": True}),
        headers={"x-api-key": tok},
    )
    assert r.status_code == 200
    assert len([c for c in calls if c > 0]) == 1  # the premium goes back once
    assert store.q("SELECT COUNT(*) n FROM model_calls")[0]["n"] == rows_before + 1  # booked once
    assert sid not in gw._inflight and budget.premium_total() == 0


# --- round 2 of the review: probes, cancelled reads, a send that fails -----------------------


def _half_open_ready(gw: Gateway, store: Store, cfg: Config) -> Any:
    """A backend breaker for the session's preset, open and past its cool-down, so the next
    call's gate claims the half-open probe."""
    from datetime import timedelta

    from vigild.breakers import Breakers, Kind
    from vigild.db import utcnow

    now = [utcnow()]
    gw.breakers = Breakers(store, cfg, clock=lambda: now[0])
    gw.breakers.trip(Kind.BACKEND, "backend:claude-sonnet", {})
    now[0] += timedelta(seconds=cfg.vigild.breakers.backend_cooldown_seconds + 1)
    return gw.breakers


def _probe_state(gw: Gateway) -> str:
    from vigild.breakers import Kind

    b = gw.breakers._row(Kind.BACKEND, "backend:claude-sonnet")
    assert b is not None
    return str(b.state)


def test_a_preflight_cancelled_on_a_half_open_backend_releases_the_probe(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float], cfg: Config, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    sid, tok = _primed(client, store, budget, gw, upstream, clock)
    _half_open_ready(gw, store, cfg)
    gate, claimed = threading.Event(), threading.Event()
    real = gw._backend_gate

    def slow_gate(preset_name: str, session_id: str | None = None) -> str | None:
        scope = real(preset_name, session_id)  # claims the probe
        claimed.set()
        gate.wait(5)
        return scope

    monkeypatch.setattr(gw, "_backend_gate", slow_gate)

    async def run() -> None:
        raw = json.dumps(_second()).encode()
        task = asyncio.create_task(gw.forward(gw.authorize(tok), "/v1/messages", {}, raw))
        while not claimed.is_set():
            await asyncio.sleep(0.01)
        assert _probe_state(gw) == "half_open"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        gate.set()
        for _ in range(100):
            if _probe_state(gw) == "open":
                break
            await asyncio.sleep(0.02)

    asyncio.run(run())
    assert _probe_state(gw) == "open" and sid not in gw._inflight


class _Blocking(httpx2.AsyncByteStream):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> Any:
        self.started.set()
        await asyncio.Event().wait()
        yield b""

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("path", "status"), [("/v1/messages", 500), ("/v1/messages/count_tokens", 200)]
)
def test_a_cancelled_body_read_releases_the_hold_the_premium_the_probe_and_closes(
    path: str, status: int, client: TestClient, gw: Gateway, store: Store, budget: Budget,
    upstream: Upstream, clock: list[float], cfg: Config,
) -> None:  # fmt: skip
    sid, tok = _primed(client, store, budget, gw, upstream, clock)
    _half_open_ready(gw, store, cfg)
    body_stream = _Blocking()
    gw.async_client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(lambda req: httpx2.Response(status, stream=body_stream))
    )

    async def run() -> None:
        raw = json.dumps(_second()).encode()
        task = asyncio.create_task(gw.forward(gw.authorize(tok), path, {}, raw))
        await asyncio.wait_for(body_stream.started.wait(), 5)  # the body read is blocked
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert sid not in gw._inflight and budget.premium_total() == 0
    assert _probe_state(gw) != "half_open" and body_stream.closed  # claimed, never left held


def test_a_send_that_fails_before_the_response_starts_still_releases_exactly_once(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float], monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    from vigild.gateway.app import create_gateway_app

    sid, tok = _primed(client, store, budget, gw, upstream, clock)
    upstream.stream = True
    released: list[float] = []
    real = budget.release_premium
    monkeypatch.setattr(budget, "release_premium", lambda s, a: (released.append(a), real(s, a))[1])

    async def run() -> None:
        payload = json.dumps({**_second(), "stream": True}).encode()
        sent = False

        async def receive() -> dict[str, Any]:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": payload, "more_body": False}
            await asyncio.Event().wait()
            return {"type": "http.disconnect"}

        async def send(msg: dict[str, Any]) -> None:
            raise OSError("client gone")

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1", "method": "POST", "path": "/v1/messages",
            "raw_path": b"/v1/messages", "query_string": b"", "root_path": "",
            "scheme": "http", "server": ("test", 80), "client": ("c", 1),
            "headers": [(b"x-api-key", tok.encode()), (b"content-type", b"application/json")],
        }  # fmt: skip
        try:
            await asyncio.wait_for(create_gateway_app(gw)(scope, receive, send), 5)
        except BaseException as e:  # the failed send surfaces however the framework reports it
            assert not isinstance(e, asyncio.TimeoutError)

    asyncio.run(run())
    assert sid not in gw._inflight and budget.premium_total() == 0
    assert len([a for a in released if a > 0]) == 1


# --- vi-0019 A1, step (a): the last completed call's prefix, and recorded holds --------
#
# s-c6578bd1c4 (2026-11-01, 13:23:49-13:24:26 UTC): call 3 (id 1922) reported
# 2 / 50,029 read / 2,088 written (5m); call 4 (id 1923) was in flight when call 5 was
# issued, and call 5 was refused: held as a full miss, $0.1672 left, under the floor.

A1_IN, A1_READ, A1_WRITE = 2, 50_029, 2_088
A1_LEFT = 0.1672  # the session's reservation left after call 4's hold (the refusal's figure)


def _third(n: int = 30_000) -> dict[str, Any]:
    """Call 5: call 4's messages, call 4's answer, and a new tail."""
    body = _second(n)
    return {
        **body,
        "messages": [
            *body["messages"],
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
            {"role": "user", "content": [{"type": "text", "text": "z" * 3_000}]},
        ],
    }


def test_a1s_fifth_call_while_the_fourth_is_in_flight_holds_the_prefix_at_the_read_rate(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """Call 5 is held at the read rate for the prefix call 3 reported as cached (its
    50,029 reads and 2,088 writes, which is what call 4 then read: 52,117), not as a full
    miss, so A1's $0.1672 admits it above the output floor."""
    up = upstream
    up.usage = {
        "input_tokens": A1_IN,
        "cache_read_input_tokens": A1_READ,
        "cache_creation": {"ephemeral_5m_input_tokens": A1_WRITE},
    }
    first_cost = _usd(
        gw, tokens_in=A1_IN, tokens_cache_read=A1_READ, tokens_cache_write_5m=A1_WRITE,
        tokens_out=up.usage_out,
    )  # fmt: skip
    tail4 = _tail_tokens(_first(), _second())
    hold4 = _usd(
        gw, tokens_cache_read=A1_READ + A1_WRITE, tokens_cache_write_5m=A1_IN + tail4,
        tokens_out=OUT,
    )  # fmt: skip
    up.count = A1_IN + A1_READ + A1_WRITE  # call 3's exact count: no overshoot
    _sid, tok = _sess(store, budget, gw, first_cost + hold4 + A1_LEFT)
    assert _post(client, tok, _first()).status_code == 200
    clock[0] += 3
    four = _pre(gw, tok, _second(), keep=True)  # call 4, in flight
    try:
        assert four.amount == pytest.approx(hold4)
        five = _pre(gw, tok, _third(), keep=True)  # call 5, issued while call 4 is in flight
        try:
            tail5 = _tail_tokens(_first(), _third())
            assert five.cached_tokens == A1_READ + A1_WRITE == 52_117
            assert five.body["max_tokens"] >= 4096  # admitted above the floor
            assert five.amount == pytest.approx(
                _usd(
                    gw, tokens_cache_read=52_117, tokens_cache_write_5m=A1_IN + tail5,
                    tokens_out=five.body["max_tokens"],
                )
            )  # fmt: skip
            assert five.amount <= A1_LEFT + 1e-9
            assert five.reason == "prefix"
        finally:
            gw.release(five)
    finally:
        gw.release(four)


def test_a1s_fifth_call_forced_to_miss_overshoots_by_at_most_its_premium_and_pages(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """The same call 5, but the provider had lost the prefix and wrote all of it again:
    the excess over its task hold is at most its miss premium, it is `settle_excess`
    (`cache_miss`), it pages, and the task's later calls are held as misses."""
    up = upstream
    up.usage = {
        "input_tokens": A1_IN,
        "cache_read_input_tokens": A1_READ,
        "cache_creation": {"ephemeral_5m_input_tokens": A1_WRITE},
    }
    up.count = A1_IN + A1_READ + A1_WRITE  # call 3's exact count: no overshoot
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200
    clock[0] += 3
    four = _pre(gw, tok, _second(), keep=True)  # call 4, in flight
    try:
        five = _pre(gw, tok, _third())
        premium = five.premium
        assert premium > 0
        tail5 = _tail_tokens(_first(), _third())
        up.usage = {
            "input_tokens": A1_IN,
            "cache_creation": {"ephemeral_5m_input_tokens": A1_READ + A1_WRITE + tail5},
        }
        assert _post(client, tok, _third()).status_code == 200  # call 5, a miss
    finally:
        gw.release(four)
    (ev,) = [e for e in store.events() if e.type == "settle_excess"]
    assert ev.data["reason"] == "cache_miss"
    assert 0 < ev.data["excess_usd"] <= premium + 1e-9
    (page,) = [i for i in store.list_inbox() if i.kind == "page"]
    assert "overshoot" in page.title
    h = _pre(gw, tok, _third())
    assert h.cached_tokens == 0 and h.premium == 0 and h.reason == "task_miss"


def test_every_metered_call_records_its_hold_and_why(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """`model_calls.hold_usd` and `hold_reason`: a first call counted by the provider is
    `count`; a call whose prefix matched is `prefix`; a call whose count failed is
    `estimate`; each row's hold_usd is the hold placed for it."""
    _reads(upstream, 20_000)
    _sid, tok = _sess(store, budget, gw, 1.0)
    first_hold = _pre(gw, tok, _first()).amount
    assert _post(client, tok, _first()).status_code == 200
    second_hold = _pre(gw, tok, _second()).amount
    assert _post(client, tok, _second()).status_code == 200
    upstream.count_status = 500
    _sid2, tok2 = _sess(store, budget, gw, 1.0)
    third_hold = _pre(gw, tok2, _first()).amount
    assert _post(client, tok2, _first()).status_code == 200
    rows = store.q("SELECT session_id, hold_usd, hold_reason FROM model_calls ORDER BY id")
    assert [r["hold_reason"] for r in rows] == ["count", "prefix", "estimate"]
    for r, held in zip(rows, (first_hold, second_hold, third_hold), strict=True):
        assert r["hold_usd"] == pytest.approx(held)


# --- prefix match on Claude Code-shaped requests (owner, 2026-11-01; the w3 finding) -------
#
# Placeholder content only: the structure (system block list with a marker, tools, user and
# assistant turns with tool_use and tool_result blocks, where the markers sit) follows the
# real requests; no prompt text.

MARK = {"type": "ephemeral"}


def _cc_turns(k: int) -> list[dict[str, Any]]:
    """k rounds: a user turn, then an assistant tool call and its result."""
    msgs: list[dict[str, Any]] = [
        {"role": "user", "content": [{"type": "text", "text": "TASK " + "p" * 6_000}]}
    ]
    for i in range(k):
        msgs.append({"role": "assistant", "content": [
            {"type": "text", "text": f"step {i}"},
            {"type": "tool_use", "id": f"tu_{i}", "name": "Read", "input": {"file": f"f{i}"}},
        ]})  # fmt: skip
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"tu_{i}", "content": "r" * 3_000},
        ]})  # fmt: skip
    return msgs


def _cc(msgs: list[dict[str, Any]], marker_at: int) -> dict[str, Any]:
    body = {
        "model": MODEL,
        "max_tokens": OUT,
        "system": [{"type": "text", "text": "SYSTEM " + "s" * 4_000, "cache_control": MARK}],
        "tools": [{"name": "Read", "description": "d", "input_schema": {"type": "object"}}],
        "messages": json.loads(json.dumps(msgs)),
    }
    if marker_at >= 0:
        body["messages"][marker_at]["content"][-1]["cache_control"] = MARK
    return body


def _cc_session(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, up: Upstream,
    first: dict[str, Any],
) -> str:  # fmt: skip
    up.usage = {"input_tokens": 3, "cache_read_input_tokens": 7_000,
                "cache_creation": {"ephemeral_5m_input_tokens": 2_000}}  # fmt: skip
    up.count = 9_003
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, first).status_code == 200
    return tok


def test_a_marker_moved_to_the_newest_message_still_matches_the_prefix(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """The owner's hypothesis: request N has its marker on its last message k; request N+1
    repeats messages 0..k without it and adds new ones, marker on the newest. The match
    ignores markers: prefix pricing, hold_reason=prefix."""
    turns = _cc_turns(3)
    n = _cc(turns[:5], marker_at=4)
    tok = _cc_session(client, gw, store, budget, upstream, n)
    clock[0] += 10
    n1 = _cc(turns, marker_at=6)
    h = _pre(gw, tok, n1)
    assert h.reason == "prefix" and h.cached_tokens == 9_000


def test_a_rewritten_message_after_the_previous_marker_still_matches_up_to_the_marker(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """Request N's marker sits on message k and an unmarked message follows it (a per-turn
    note); request N+1 rewrites that message. Everything up to the marker is what the
    provider cached, so the match holds there: prefix, the rest estimated at the write rate."""
    turns = _cc_turns(3)
    note = {"role": "user", "content": [{"type": "text", "text": "NOTE " + "n" * 500}]}
    n = _cc([*turns[:5], note], marker_at=4)
    tok = _cc_session(client, gw, store, budget, upstream, n)
    clock[0] += 10
    rewritten = {"role": "user", "content": [{"type": "text", "text": "NOTE2 " + "m" * 400}]}
    n1 = _cc([*turns[:5], rewritten, *turns[5:]], marker_at=7)
    h = _pre(gw, tok, n1)
    assert h.reason == "prefix" and h.cached_tokens == 9_000
    # everything after the previous marker anew, plus the previous call's uncached input
    rest = math.ceil((prefix_shape(n1).chars - prefix_shape(n).cum[4]) / CHARS_PER_TOKEN)
    assert h.amount == pytest.approx(
        _usd(gw, tokens_cache_read=9_000, tokens_cache_write_5m=3 + rest, tokens_out=OUT)
    )


def test_a_marker_prefix_the_provider_did_not_cache_is_held_at_the_write_rate(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """Review round 1, finding 1: the previous call reported no cache use (a prefix under the
    model's minimum, a failed write). Matching up to its marker must not make that prefix
    free: all of its input is held at the write rate, plus what follows the marker."""
    turns = _cc_turns(3)
    note = {"role": "user", "content": [{"type": "text", "text": "NOTE " + "n" * 500}]}
    n = _cc([*turns[:5], note], marker_at=4)
    upstream.usage = {"input_tokens": 9_000}
    upstream.count = 9_000
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, n).status_code == 200
    clock[0] += 10
    n1 = _cc([*turns[:5], *turns[5:]], marker_at=6)
    h = _pre(gw, tok, n1)
    rest = math.ceil((prefix_shape(n1).chars - prefix_shape(n).cum[4]) / CHARS_PER_TOKEN)
    assert h.reason == "prefix" and h.cached_tokens == 0
    assert h.amount == pytest.approx(_usd(gw, tokens_cache_write_5m=9_000 + rest, tokens_out=OUT))


def test_a_cache_control_key_inside_a_tool_input_is_not_a_marker() -> None:
    """Review round 1, finding 2: only a message's own or its top-level blocks' markers
    count; a `cache_control` key in a tool's input is data."""
    turns = _cc_turns(2)
    body = _cc(turns, marker_at=2)
    body["messages"][3]["content"][1]["input"]["cache_control"] = MARK
    assert prefix_shape(body).marker == 2


@pytest.mark.parametrize("change", ["system", "message"])
def test_a_missed_prefix_records_where_it_diverged_and_no_content(
    change: str, client: TestClient, gw: Gateway, store: Store, budget: Budget,
    upstream: Upstream, clock: list[float],
) -> None:  # fmt: skip
    """The diagnostic: a miss records the first diverging part (a head part, or a message
    index and its role) as names and indexes only; the hold stays miss-priced (count)."""
    turns = _cc_turns(2)
    n = _cc(turns[:3], marker_at=2)
    tok = _cc_session(client, gw, store, budget, upstream, n)
    clock[0] += 10
    n1 = _cc(turns, marker_at=4)
    if change == "system":
        n1["system"][0]["text"] = "SYSTEM CHANGED " + "s" * 10
    else:
        n1["messages"][1]["content"][0]["text"] = "edited step"
    h = _pre(gw, tok, n1)
    assert h.reason == "count"
    (ev,) = [e for e in store.events() if e.type == "prefix_miss"]
    if change == "system":
        assert ev.data["part"] == "system" and ev.data["index"] is None
    else:
        assert ev.data["part"] == "message" and ev.data["index"] == 1
        assert ev.data["role"] == "assistant"
    blob = json.dumps(ev.data)
    for text in ("SYSTEM", "edited", "TASK", "ppp", "rrr"):
        assert text not in blob


def test_a_miss_records_no_role_it_does_not_know_and_nothing_without_a_record(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """Review round 1, findings 3 and 8: the event copies a role only if it is user or
    assistant; a session's first call (no previous record) records nothing."""
    turns = _cc_turns(2)
    n = _cc(turns[:3], marker_at=2)
    _sid, tok = _sess(store, budget, gw, 1.0)
    _pre(gw, tok, n)
    assert not [e for e in store.events() if e.type == "prefix_miss"]
    upstream.usage = {"input_tokens": 3, "cache_read_input_tokens": 7_000}
    assert _post(client, tok, n).status_code == 200
    clock[0] += 10
    n1 = _cc(turns, marker_at=4)
    n1["messages"][1]["role"] = "SECRET-LIKE " + "x" * 50
    _pre(gw, tok, n1)
    (ev,) = [e for e in store.events() if e.type == "prefix_miss"]
    assert ev.data["index"] == 1 and ev.data["role"] is None
    assert "SECRET" not in json.dumps(ev.data)


# --- the provider must read what the hold prices at the read rate (owner, 2026-11-01) ----


def _guard_session(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, up: Upstream,
    clock: list[float],
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:  # fmt: skip
    """The previous call: marker on message 4 (a tool result); 9 rounds of turns to follow."""
    turns = _cc_turns(9)
    n = _cc(turns[:5], marker_at=4)
    tok = _cc_session(client, gw, store, budget, up, n)
    clock[0] += 10
    return tok, turns, n


def test_the_same_prefix_without_a_marker_on_the_new_request_is_held_as_a_miss(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """No breakpoint at or after the matched prefix's end: the provider will not read it."""
    tok, turns, _n = _guard_session(client, gw, store, budget, upstream, clock)
    h = _pre(gw, tok, _cc(turns[:7], marker_at=-1))
    assert h.reason == "count" and h.cached_tokens == 0
    (ev,) = [e for e in store.events() if e.type == "prefix_miss"]
    assert ev.data["part"] == "no_marker"


def test_a_new_marker_21_blocks_past_the_old_one_is_held_as_a_miss(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """The provider looks back 20 blocks from a breakpoint: 21 blocks past the previous
    marker (7 rounds of 3 blocks) it does not find the cached prefix."""
    tok, turns, _n = _guard_session(client, gw, store, budget, upstream, clock)
    h = _pre(gw, tok, _cc(turns, marker_at=18))
    assert h.reason == "count" and h.cached_tokens == 0
    (ev,) = [e for e in store.events() if e.type == "prefix_miss"]
    assert ev.data["part"] == "lookback"


def test_a_new_marker_3_blocks_past_the_old_one_is_held_as_a_prefix(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """One round later (3 blocks), well within the lookback: read-rate pricing."""
    tok, turns, _n = _guard_session(client, gw, store, budget, upstream, clock)
    h = _pre(gw, tok, _cc(turns[:7], marker_at=6))
    assert h.reason == "prefix" and h.cached_tokens == 9_000
    assert not [e for e in store.events() if e.type == "prefix_miss"]


@pytest.mark.parametrize(
    ("marker_at", "distance", "reason"), [(17, 20, "prefix"), (18, 21, "count")]
)
def test_the_lookback_boundary_is_20_blocks(
    marker_at: int, distance: int, reason: str, client: TestClient, gw: Gateway, store: Store,
    budget: Budget, upstream: Upstream, clock: list[float],
) -> None:  # fmt: skip
    """Review: exactly 20 blocks past the previous marker is still read; 21 is not."""
    tok, turns, n = _guard_session(client, gw, store, budget, upstream, clock)
    n1 = _cc(turns, marker_at=marker_at)
    new = prefix_shape(n1)
    assert max(new.marks) - prefix_shape(n).prefix_end() == distance
    assert _pre(gw, tok, n1).reason == reason

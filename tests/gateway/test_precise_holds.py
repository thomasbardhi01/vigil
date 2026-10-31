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

import json
import math
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from tests.gateway.test_gateway import PA, _session, budget, client, gw  # noqa: F401
from vigild.budget import Budget
from vigild.config import Config
from vigild.db import Store
from vigild.gateway.service import CHARS_PER_TOKEN, Gateway, GatewayError, prefix_digest
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

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def __call__(self, req: httpx2.Request) -> httpx2.Response:
        self.requests.append(req)
        if req.url.path.endswith("/count_tokens"):
            if self.count_raises is not None:
                raise self.count_raises
            if self.count_status != 200:
                return httpx2.Response(self.count_status, json={"type": "error"})
            return httpx2.Response(200, json={"input_tokens": self.count})
        if req.url.path.endswith("/tokenize"):
            return httpx2.Response(200, json={"tokens": list(range(self.tokens))})
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
    a = prefix_digest(first, len(first["messages"]))[1]
    b = prefix_digest(second, len(second["messages"]))[1]
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
    clock[0] += 3 * MIN
    second = _second(n_first, 4_500)
    tail = _tail_tokens(_first(n_first), second)
    expect_in = _usd(gw, tokens_cache_read=76_059, tokens_cache_write_5m=2 + 1_126 + tail)
    h = _pre(gw, tok, second, keep=True)
    try:
        assert h.amount == pytest.approx(expect_in + _usd(gw, tokens_out=OUT))
        assert h.amount - _usd(gw, tokens_out=OUT) == pytest.approx(0.014, abs=0.002)
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
    clock[0] += 10 * MIN
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
    clock[0] += 5 * MIN
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


def test_a_call_in_flight_makes_the_next_a_miss_counted_exactly(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    reads = 20_000
    _reads(upstream, reads)
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200
    upstream.count = 25_000
    a = _pre(gw, tok, _second(), keep=True)
    b = _pre(gw, tok, _second(), keep=True)  # the first is still in flight
    try:
        tail = _tail_tokens(_first(), _second())
        assert a.amount == pytest.approx(
            _usd(gw, tokens_cache_read=reads, tokens_cache_write_5m=5 + tail, tokens_out=OUT)
        )
        assert b.cached_tokens == 0 and b.premium == 0
        assert b.amount > a.amount
    finally:
        gw.release(a)
        gw.release(b)


def test_a_cache_write_never_earns_the_read_rate(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    """G1: tokens the previous call wrote are held at the write rate, not the read rate;
    its prompt total is still known from usage, not estimated."""
    upstream.usage = {"input_tokens": 5, "cache_creation": {"ephemeral_5m_input_tokens": 20_000}}
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200
    tail = _tail_tokens(_first(), _second())
    h = _pre(gw, tok, _second())
    assert h.amount == pytest.approx(_usd(gw, tokens_cache_write_5m=20_005 + tail, tokens_out=OUT))
    assert h.premium == 0


def test_a_prefix_older_than_fifty_minutes_is_counted_again(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
) -> None:  # fmt: skip
    _reads(upstream, 20_000)
    _sid, tok = _sess(store, budget, gw, 1.0)
    assert _post(client, tok, _first()).status_code == 200
    clock[0] += 51 * MIN
    upstream.count = 9_999
    h = _pre(gw, tok, _second())
    assert h.amount == pytest.approx(_usd(gw, tokens_cache_write_5m=9_999, tokens_out=OUT))


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

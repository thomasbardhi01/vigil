"""#79 (a): a session's cached prefix is priced at the cache-read rate in the worst case.
(Superseded in part by `test_precise_holds.py`, owner ruling R23, 2026-10-31 (#1): what
is left here is the settling and re-reservation of a cache miss.)

The previous call of the same session wrote the prefix (the provider's usage said so),
this call resends it byte for byte (compared by hash, `cache_control` markers ignored)
within 50 minutes. The new tail stays at the 1-hour write rate. A cache miss settles
its real cost, records `settle_excess` (`cache_miss`), trips no breaker, and the
session's next call must re-reserve first.
"""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from tests.gateway.test_gateway import PA, _session, budget, client, gw  # noqa: F401
from vigild.breakers import GLOBAL, Breakers, Kind
from vigild.budget import Budget
from vigild.config import Config
from vigild.db import Store
from vigild.gateway.service import Gateway, worst_case_usd
from vigild.jobs.model import Role

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


def _read(up: Upstream, n: int = 20_000) -> None:
    """The provider reports n cache reads (G1: only reads earn the read rate)."""
    up.usage = {"input_tokens": 5, "cache_read_input_tokens": n}


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

    prefix = [
        body.get("model"),
        body.get("thinking"),
        strip(body.get("tools")),
        strip(body.get("system")),
        strip(body["messages"][:n]),
    ]
    return len(json.dumps(prefix, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def _plain(gw: Gateway, raw_len: int) -> float:
    return worst_case_usd(gw.prices, MODEL, raw_len, 4096)


def _miss(client: TestClient, gw: Gateway, tok: str, up: Upstream, clock: list[float]) -> None:
    _read(up)
    assert _post(client, tok, _first()).status_code == 200
    clock[0] += 4 * MIN
    # the provider did not have the prefix: it wrote everything again
    up.usage = {"input_tokens": 5, "cache_creation": {"ephemeral_1h_input_tokens": 14_000}}
    assert _post(client, tok, _second()).status_code == 200


def _no_room_at_the_miss(budget: Budget, monkeypatch: pytest.MonkeyPatch) -> None:
    """The caps refuse the excess's immediate reservation (`_learn`): the session owes it."""

    def refused(sid: str, premium: float, **kw: Any) -> bool:
        budget.release_premium(sid, premium)
        return False

    monkeypatch.setattr(budget, "swap_premium", refused)


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    _no_room_at_the_miss(budget, monkeypatch)
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


def _plain_hold(gw: Gateway, raw_len: int, out: int = 4096) -> float:
    return worst_case_usd(gw.prices, MODEL, raw_len, out)


def test_revoking_a_session_drops_what_a_miss_owes(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    _no_room_at_the_miss(budget, monkeypatch)
    sid, tok = _session(store, budget, gw)
    _miss(client, gw, tok, upstream, clock)
    assert gw._rereserve.get(sid, 0) > 0
    gw.revoke(sid)
    assert sid not in gw._rereserve


def _task_session(store: Store, budget: Budget, gw: Gateway, amount: float) -> tuple[str, str]:
    job = store.create_job(repo=PA, base="main", title="t", request="r", notes=[])
    store.create_task(job.id, {"task_id": "t-cap"}, "claude")
    s = store.create_session(job.id, Role.WORKER, task_id="t-cap", backend_preset="claude-sonnet")
    budget.reserve(session_id=s.id, task_id="t-cap", amount=amount, purpose="worker")
    return s.id, gw.issue_token(s.id, PA, "claude-sonnet")


def test_a_re_reservation_the_task_cap_cannot_take_is_refused(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    cfg: Config, clock: list[float],
) -> None:  # fmt: skip
    _sid, tok = _task_session(store, budget, gw, cfg.budgets.per_task_usd - 0.001)
    _miss(client, gw, tok, upstream, clock)
    r = _post(client, tok, _first())
    assert r.status_code == 403 and "budget" in r.json()["error"]["message"]
    assert "per_task" in r.json()["error"]["message"] or "task" in r.json()["error"]["message"]


def test_a_re_reservation_the_month_cannot_take_is_refused(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    clock: list[float],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    _no_room_at_the_miss(budget, monkeypatch)
    _sid, tok = _session(store, budget, gw)
    _miss(client, gw, tok, upstream, clock)
    budget.cfg.monthly_usd = budget.spent_month() + budget.open_month()
    r = _post(client, tok, _first())
    assert r.status_code == 403 and "budget" in r.json()["error"]["message"]


def test_no_cap_changes_after_a_hit_or_a_miss(
    client: TestClient, gw: Gateway, store: Store, budget: Budget, upstream: Upstream,
    cfg: Config, clock: list[float],
) -> None:  # fmt: skip
    """G3: the limits `reserve` checks are the same before and after."""
    before = budget.cfg.model_dump()
    _sid, tok = _session(store, budget, gw)
    _read(upstream)
    assert _post(client, tok, _first()).status_code == 200
    assert _post(client, tok, _second()).status_code == 200  # a hit
    assert budget.cfg.model_dump() == before
    _miss(client, gw, tok, upstream, clock)
    assert budget.cfg.model_dump() == before
    # and they still bind: a reservation past the day is refused
    from vigild.budget import BudgetExceeded

    with pytest.raises(BudgetExceeded):
        budget.reserve(session_id=None, task_id=None, amount=before["daily_usd"] + 1, purpose="x")

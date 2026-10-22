"""The model gateway (P1): containers hold a session token, never a provider key."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from vigild.budget import Budget
from vigild.config import Config, Secrets
from vigild.db import Store
from vigild.gateway.app import create_gateway_app
from vigild.gateway.service import Gateway, GatewayError
from vigild.jobs.model import Role

FAKE_KEY = "fake-provider-key-for-tests"
PA = "thomasbardhi01/parkagent"


class Upstream:
    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.stream = False
        self.status = 200

    def __call__(self, req: httpx2.Request) -> httpx2.Response:
        self.requests.append(req)
        if self.status != 200:
            return httpx2.Response(
                self.status, json={"type": "error", "error": {"type": "overloaded_error"}}
            )
        if req.url.path.endswith("/count_tokens"):
            return httpx2.Response(200, json={"input_tokens": 12})
        body = json.loads(req.content)
        if body.get("stream"):
            events = [
                {
                    "type": "message_start",
                    "message": {
                        "model": body["model"],
                        "usage": {
                            "input_tokens": 1000,
                            "output_tokens": 1,
                            "cache_read_input_tokens": 5000,
                        },
                    },
                },
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 300},
                },
                {"type": "message_stop"},
            ]
            data = b"".join(
                f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in events
            )
            return httpx2.Response(200, content=data, headers={"content-type": "text/event-stream"})
        return httpx2.Response(
            200,
            json={
                "model": body["model"],
                "content": [{"type": "text", "text": '{"answer": "S", "probability": 0.9}'}],
                "usage": {"input_tokens": 200, "output_tokens": 50},
            },
        )


@pytest.fixture
def upstream() -> Upstream:
    return Upstream()


@pytest.fixture
def budget(cfg: Config, store: Store) -> Budget:
    return Budget(store, cfg.budgets)


@pytest.fixture
def gw(cfg: Config, store: Store, budget: Budget, upstream: Upstream) -> Gateway:
    transport = httpx2.MockTransport(upstream)
    return Gateway(
        cfg,
        store,
        budget,
        Secrets({"ANTHROPIC_API_KEY": FAKE_KEY}),
        transport=transport,
        async_transport=transport,
    )


@pytest.fixture
def client(gw: Gateway) -> Iterator[TestClient]:
    with TestClient(create_gateway_app(gw)) as c:
        yield c


def _session(
    store: Store,
    budget: Budget,
    gw: Gateway,
    amount: float = 1.0,
    repo: str = PA,
    preset: str = "claude-sonnet",
) -> tuple[str, str]:
    s = store.create_session(None, Role.WORKER, backend_preset=preset)
    budget.reserve(session_id=s.id, task_id=f"t-{s.id}", amount=amount, purpose="worker")
    return s.id, gw.issue_token(s.id, repo, preset)


def _msg(**kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "claude-sonnet-5-5",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": "hi"}],
    }
    body.update(kw)
    return body


def test_forwards_with_the_real_key_and_meters(
    client: TestClient, store: Store, budget: Budget, gw: Gateway, upstream: Upstream
) -> None:
    sid, tok = _session(store, budget, gw)
    r = client.post(
        "/v1/messages",
        json=_msg(),
        headers={"authorization": f"Bearer {tok}", "anthropic-version": "2023-06-01"},
    )
    assert r.status_code == 200
    sent = upstream.requests[0]
    assert sent.headers["x-api-key"] == FAKE_KEY
    assert "authorization" not in sent.headers
    assert sent.headers["anthropic-version"] == "2023-06-01"
    assert str(sent.url) == "https://api.anthropic.com/v1/messages"
    row = store.q("SELECT * FROM model_calls")[0]
    assert (row["session_id"], row["tokens_in"], row["tokens_out"]) == (sid, 200, 50)
    assert row["cost_usd"] == pytest.approx(200 * 2e-6 + 50 * 1e-5)
    assert store.get_session(sid).cost_usd == pytest.approx(row["cost_usd"])
    assert FAKE_KEY not in r.text


def test_x_api_key_header_also_authenticates(
    client: TestClient, store: Store, budget: Budget, gw: Gateway
) -> None:
    _, tok = _session(store, budget, gw)
    assert client.post("/v1/messages", json=_msg(), headers={"x-api-key": tok}).status_code == 200


def test_streaming_is_proxied_and_metered(
    client: TestClient, store: Store, budget: Budget, gw: Gateway
) -> None:
    sid, tok = _session(store, budget, gw)
    with client.stream(
        "POST", "/v1/messages", json=_msg(stream=True), headers={"x-api-key": tok}
    ) as r:
        body = b"".join(r.iter_bytes())
    assert b"message_stop" in body
    row = store.q("SELECT * FROM model_calls WHERE session_id=?", (sid,))[0]
    assert (row["tokens_in"], row["tokens_out"], row["tokens_cache_read"]) == (1000, 300, 5000)


def test_missing_bad_or_revoked_token_is_401(
    client: TestClient, store: Store, budget: Budget, gw: Gateway, upstream: Upstream
) -> None:
    assert client.post("/v1/messages", json=_msg()).status_code == 401
    assert (
        client.post("/v1/messages", json=_msg(), headers={"x-api-key": "nope"}).status_code == 401
    )
    sid, tok = _session(store, budget, gw)
    gw.revoke(sid)
    assert client.post("/v1/messages", json=_msg(), headers={"x-api-key": tok}).status_code == 401
    assert upstream.requests == []


def test_api_tokens_do_not_work_on_the_gateway(client: TestClient) -> None:
    # The gateway knows only session tokens.
    assert (
        client.post("/v1/messages", json=_msg(), headers={"x-api-key": FAKE_KEY}).status_code == 401
    )


def test_call_that_would_cross_the_reservation_is_refused_before_it_is_sent(
    client: TestClient, store: Store, budget: Budget, gw: Gateway, upstream: Upstream
) -> None:
    sid, tok = _session(store, budget, gw, amount=0.05)
    r = client.post("/v1/messages", json=_msg(max_tokens=64000), headers={"x-api-key": tok})
    assert r.status_code == 403 and "budget" in r.text
    assert upstream.requests == []
    assert any(e.type == "gateway_refused" for e in store.events(session_id=sid))


def test_model_the_repo_does_not_allow_is_refused(
    client: TestClient, store: Store, budget: Budget, gw: Gateway, upstream: Upstream
) -> None:
    _, tok = _session(store, budget, gw)
    r = client.post("/v1/messages", json=_msg(model="claude-mystery-9"), headers={"x-api-key": tok})
    assert r.status_code == 403 and upstream.requests == []


def test_private_repo_rule_on_the_wire(
    client: TestClient, cfg: Config, store: Store, budget: Budget, gw: Gateway, upstream: Upstream
) -> None:
    _, tok = _session(store, budget, gw)
    cfg.repos.repos[PA].backends = ["claude-opus"]  # policy changed after the token was issued
    r = client.post("/v1/messages", json=_msg(), headers={"x-api-key": tok})
    assert r.status_code == 403 and "does not list" in r.text
    assert upstream.requests == []


def test_only_messages_endpoints_exist(
    client: TestClient, store: Store, budget: Budget, gw: Gateway
) -> None:
    _, tok = _session(store, budget, gw)
    assert client.post("/v1/complete", json={}, headers={"x-api-key": tok}).status_code == 404
    assert client.get("/v1/models", headers={"x-api-key": tok}).status_code in (404, 405)


def test_count_tokens_is_forwarded_and_free(
    client: TestClient, store: Store, budget: Budget, gw: Gateway
) -> None:
    _, tok = _session(store, budget, gw)
    r = client.post("/v1/messages/count_tokens", json=_msg(), headers={"x-api-key": tok})
    assert r.status_code == 200 and r.json() == {"input_tokens": 12}
    assert store.q("SELECT COUNT(*) n FROM model_calls")[0]["n"] == 0


def test_upstream_error_passes_through(
    client: TestClient, store: Store, budget: Budget, gw: Gateway, upstream: Upstream
) -> None:
    _, tok = _session(store, budget, gw)
    upstream.status = 529
    assert client.post("/v1/messages", json=_msg(), headers={"x-api-key": tok}).status_code == 529


def test_missing_provider_key_is_503(
    cfg: Config, store: Store, budget: Budget, upstream: Upstream
) -> None:
    t = httpx2.MockTransport(upstream)
    gw = Gateway(cfg, store, budget, Secrets({}), transport=t, async_transport=t)
    with TestClient(create_gateway_app(gw)) as c:
        _, tok = _session(store, budget, gw)
        assert c.post("/v1/messages", json=_msg(), headers={"x-api-key": tok}).status_code == 503


def test_internal_call_reserves_meters_and_settles(
    gw: Gateway, store: Store, budget: Budget, upstream: Upstream
) -> None:
    reply = gw.call(
        repo=PA,
        preset="claude-haiku",
        body={"max_tokens": 100, "messages": [{"role": "user", "content": "q"}]},
        purpose="decider",
        job_id=None,
    )
    assert reply["content"][0]["type"] == "text"
    assert json.loads(upstream.requests[0].content)["model"] == "claude-haiku-5-5"
    row = store.q("SELECT purpose, model FROM model_calls")[0]
    assert (row["purpose"], row["model"]) == ("decider", "claude-haiku-5-5")
    assert budget.open_today() == 0 and budget.spent_today() > 0


def test_internal_call_refuses_a_repo_route_not_listed(gw: Gateway, cfg: Config) -> None:
    cfg.repos.repos[PA].backends = ["claude-sonnet"]
    with pytest.raises(GatewayError):
        gw.call(
            repo=PA,
            preset="claude-haiku",
            body={"max_tokens": 10, "messages": []},
            purpose="decider",
            job_id=None,
        )


def test_internal_call_is_refused_when_the_day_is_spent(gw: Gateway, budget: Budget) -> None:
    budget.reserve(session_id="big", task_id="t1", amount=2.0, purpose="worker")
    budget.reserve(session_id="big2", task_id="t2", amount=2.0, purpose="worker")
    budget.reserve(session_id="big3", task_id="t3", amount=1.0, purpose="worker")
    with pytest.raises(GatewayError, match="daily"):
        gw.call(
            repo=PA,
            preset="claude-haiku",
            body={"max_tokens": 10, "messages": []},
            purpose="decider",
            job_id=None,
        )

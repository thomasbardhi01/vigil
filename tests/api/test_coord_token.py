"""Issue #146: a separate coord API token. vigild derives the actor from the token, never
from the body. The coord token approves only with a cited ruling and is refused outright
for budget or cap edits, rung changes, merges and any spec that touches the repo's
`ladder_pinned_paths`. The owner token is unchanged. Tokens are generated per test."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from tests.conftest import RecordingRunner, auth
from vigild.api.app import create_app
from vigild.api.auth import Scope, identify, require
from vigild.config import Config
from vigild.db import Store
from vigild.jobs import decisions
from vigild.jobs.model import JobState
from vigild.services import Services, Tokens

PA = "thomasbardhi01/parkagent"
RULING = "owner ruling 2026-10-29: docs-only specs are approved by coord"


def _job(n: int = 1, **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "repo": PA,
        "title": f"Document limit {n}",
        "request": "The rate limits are undocumented.",
        "why": "support asks weekly",
        "value": 3,
        "risk": 1,
    }
    return body | over


def _spec_item(store: Store, job_id: str, scope: list[str] | None = None) -> int:
    """What the coord's filing leaves: the spec, the plan, the gate's pass and the item."""
    plan = _plan(scope or ["docs/a.md"])
    for name, content in (("spec.md", "s"), ("plan.md", plan), ("spec_gate.json", '{"ok": true}')):
        store.add_artifact(job_id, name, content, "human")
    return store.create_inbox_item("specs", "spec", job_id, "spec", {}).id


def _plan(scope: list[str]) -> str:
    return "# plan\n```json\n" + json.dumps({"workers": [{"files_in_scope": scope}]}) + "\n```\n"


@pytest.fixture
def pending(client: TestClient, tokens: Tokens, store: Store) -> tuple[str, int]:
    jid = client.post("/api/jobs", json=_job(), headers=auth(tokens.admin)).json()["id"]
    return jid, _spec_item(store, jid)


def _state_event(store: Store, jid: str) -> Any:
    (ev,) = [
        e for e in store.events(job_id=jid) if e.type == "state" and e.data["to"] == "approved"
    ]
    return ev


def test_identify_tells_the_coord_token_from_the_owner_token(tokens: Tokens) -> None:
    assert identify(tokens, f"Bearer {tokens.admin}") is Scope.ADMIN
    assert identify(tokens, f"Bearer {tokens.coord}") is Scope.COORD
    assert identify(Tokens(admin="a", read=None, heartbeat=None), "Bearer b") is None
    # an unset coord token matches nothing, not even an empty bearer
    assert identify(Tokens(admin="a", read=None, heartbeat=None, coord=None), "Bearer ") is None


def test_refused_without_a_ruling(
    client: TestClient, tokens: Tokens, store: Store, runner: RecordingRunner,
    pending: tuple[str, int],
) -> None:  # fmt: skip
    jid, item = pending
    for body in (None, {}, {"ruling": ""}, {"ruling": "   "}, {"ruling": 5}):
        r = client.post(f"/api/inbox/{item}/approve", headers=auth(tokens.coord), json=body)
        assert r.status_code == 422 and "ruling" in r.text, body
    assert store.get_job(jid).state is JobState.SPEC_PENDING
    assert runner.approved == [] and store.get_inbox_item(item).status == "open"


def test_a_coord_approval_with_a_ruling_is_recorded_as_coord_over_mcp(
    client: TestClient, tokens: Tokens, store: Store, runner: RecordingRunner,
    pending: tuple[str, int],
) -> None:  # fmt: skip
    jid, item = pending
    r = client.post(
        f"/api/inbox/{item}/approve", headers=auth(tokens.coord), json={"ruling": RULING}
    )
    assert r.status_code == 200, r.text
    assert store.get_job(jid).state is JobState.APPROVED and runner.approved == [jid]
    state = _state_event(store, jid)
    assert (state.data["actor"], state.data["channel"]) == ("coord", "mcp")
    assert state.data["evidence"]["ruling"] == RULING
    (ap,) = store.q("SELECT * FROM approvals WHERE job_id=?", (jid,))
    assert (ap["actor"], ap["channel"]) == ("coord", "mcp")
    (ev,) = [e for e in store.events(job_id=jid) if e.type == "approval"]
    assert ev.data["ruling"] == RULING
    art = store.get_artifact(jid, decisions.NAME)
    assert art is not None
    (line,) = [json.loads(x) for x in art.content.splitlines()]
    assert (line["by"], line["kind"], line["text"]) == ("vigild", "coord_approval", RULING)
    assert store.get_inbox_item(item).resolved_by == "coord"


def test_the_actor_never_comes_from_the_body(
    client: TestClient, tokens: Tokens, store: Store, pending: tuple[str, int]
) -> None:
    jid, item = pending
    body = {"ruling": RULING, "actor": "owner", "channel": "inbox"}
    assert client.post(
        f"/api/inbox/{item}/approve", headers=auth(tokens.coord), json=body
    ).is_success
    assert _state_event(store, jid).data["actor"] == "coord"


def test_a_ruling_is_redacted_before_it_is_stored(
    client: TestClient, tokens: Tokens, store: Store, pending: tuple[str, int]
) -> None:
    jid, item = pending
    leak = "sk-ant-api03-" + "A" * 40
    r = client.post(
        f"/api/inbox/{item}/approve", headers=auth(tokens.coord), json={"ruling": f"r {leak}"}
    )
    assert r.is_success, r.text
    art = store.get_artifact(jid, decisions.NAME)
    assert art is not None and leak not in art.content
    assert leak not in _state_event(store, jid).data["evidence"]["ruling"]


def test_an_owner_approval_is_unchanged(
    client: TestClient, tokens: Tokens, store: Store, pending: tuple[str, int]
) -> None:
    jid, item = pending
    r = client.post(f"/api/inbox/{item}/approve", headers=auth(tokens.admin), json={})
    assert r.status_code == 200, r.text
    state = _state_event(store, jid)
    assert (state.data["actor"], state.data["channel"]) == ("owner", "inbox")
    assert "ruling" not in state.data["evidence"]
    (ap,) = store.q("SELECT * FROM approvals WHERE job_id=?", (jid,))
    assert (ap["actor"], ap["channel"]) == ("owner", "inbox")
    assert store.get_artifact(jid, decisions.NAME) is None


def test_refused_for_a_spec_that_hits_ladder_pinned_paths(
    client: TestClient, tokens: Tokens, store: Store, runner: RecordingRunner, cfg: Config
) -> None:
    cfg.repos.repos[PA].ladder_pinned_paths = ["vigild/gateway/**"]
    pinned = client.post("/api/jobs", json=_job(1), headers=auth(tokens.admin)).json()["id"]
    plain = client.post("/api/jobs", json=_job(2), headers=auth(tokens.admin)).json()["id"]
    ip = _spec_item(store, pinned, ["vigild/gateway/service.py"])
    iq = _spec_item(store, plain, ["docs/a.md"])
    r = client.post(f"/api/inbox/{ip}/approve", headers=auth(tokens.coord), json={"ruling": RULING})
    assert r.status_code == 403 and "ladder_pinned_paths" in r.text
    assert store.get_job(pinned).state is JobState.SPEC_PENDING and runner.approved == []
    assert store.get_inbox_item(ip).status == "open"
    # a wildcard scope that can name a pinned file counts too
    wild = client.post("/api/jobs", json=_job(3), headers=auth(tokens.admin)).json()["id"]
    iw = _spec_item(store, wild, ["vigild/**"])
    assert (
        client.post(
            f"/api/inbox/{iw}/approve", headers=auth(tokens.coord), json={"ruling": RULING}
        ).status_code
        == 403
    )
    # the owner may approve the pinned spec; the coord may approve the plain one
    assert client.post(f"/api/inbox/{ip}/approve", headers=auth(tokens.admin), json={}).is_success
    assert client.post(
        f"/api/inbox/{iq}/approve", headers=auth(tokens.coord), json={"ruling": RULING}
    ).is_success


def test_approve_all_with_the_coord_token_needs_a_ruling_and_skips_pinned_specs(
    client: TestClient, tokens: Tokens, store: Store, cfg: Config
) -> None:
    cfg.repos.repos[PA].ladder_pinned_paths = ["vigild/gateway/**"]
    out = client.post(
        "/api/batch",
        json={"name": "b", "jobs": [_job(1), _job(2)]},
        headers=auth(tokens.admin),
    ).json()
    pinned, plain = out["jobs"]
    _spec_item(store, pinned, ["vigild/gateway/service.py"])
    _spec_item(store, plain, ["docs/a.md"])
    url = f"/api/batch/{out['batch_id']}/approve-all"
    r = client.post(url, headers=auth(tokens.coord))
    assert r.status_code == 422 and "ruling" in r.text
    assert store.get_job(plain).state is JobState.SPEC_PENDING
    r = client.post(url, headers=auth(tokens.coord), json={"ruling": RULING})
    assert r.status_code == 200, r.text
    assert [x["job_id"] for x in r.json()["approved"]] == [plain]
    assert [x["job_id"] for x in r.json()["skipped"]] == [pinned]
    assert "ladder_pinned_paths" in r.json()["skipped"][0]["reason"]
    assert store.get_job(pinned).state is JobState.SPEC_PENDING
    assert _state_event(store, plain).data["actor"] == "coord"


# --- routes the coord token is refused outright ---------------------------------------
# vigild has no route yet to edit a cap or budget, move a rung or merge a PR (those are
# edits to configs/*.yaml by PR, and the owner's merge on GitHub). The refusal lives in
# `require`, keyed on the route, so a route added later is refused before its handler runs.
# These tests mount stand-ins at the places such routes would be.

WOULD_BE = [
    ("PUT", "/api/budget"),
    ("POST", "/api/budgets/caps"),
    ("PATCH", "/api/caps/task"),
    ("POST", "/api/review/ladder/rung"),
    ("PUT", "/api/review/ladder/{shape}"),
    ("POST", "/api/jobs/{job_id}/merge"),
    ("POST", "/api/merge"),
]


@pytest.fixture
def stub_app(services: Services) -> FastAPI:
    app = create_app(services)
    for method, path in WOULD_BE:
        app.add_api_route(
            path,
            lambda: {"done": True},
            methods=[method],
            dependencies=[Depends(require(Scope.ADMIN))],
        )
    return app


@pytest.mark.parametrize(
    ("method", "path"),
    [(m, p.replace("{shape}", "docs").replace("{job_id}", "pa-0001")) for m, p in WOULD_BE],
)
def test_refused_for_cap_rung_and_merge_routes(
    stub_app: FastAPI, tokens: Tokens, method: str, path: str
) -> None:
    with TestClient(stub_app) as c:
        r = c.request(method, path, headers=auth(tokens.coord), json={})
        assert r.status_code == 403 and "owner" in r.text, (method, path)
        # the same route answers the owner token
        assert c.request(method, path, headers=auth(tokens.admin), json={}).status_code == 200


def test_an_unreadable_plan_is_not_approved_by_coord(
    client: TestClient, tokens: Tokens, store: Store, pending: tuple[str, int]
) -> None:
    jid, item = pending
    store.add_artifact(jid, "plan.md", "no json block here", "human")  # scope unknown: fail closed
    r = client.post(
        f"/api/inbox/{item}/approve", headers=auth(tokens.coord), json={"ruling": RULING}
    )
    assert r.status_code == 403
    assert store.get_job(jid).state is JobState.SPEC_PENDING


def test_the_coord_token_still_reads_and_files_work(client: TestClient, tokens: Tokens) -> None:
    assert client.get("/api/health", headers=auth(tokens.coord)).status_code == 200
    r = client.post("/api/jobs", json=_job(), headers=auth(tokens.coord))
    assert r.status_code == 202
    assert client.get("/api/review/ladder", headers=auth(tokens.coord)).status_code == 200


def test_the_coord_token_cannot_log_in_to_the_ui(ui_client: TestClient, tokens: Tokens) -> None:
    r = ui_client.post("/api/login", json={"token": tokens.coord})
    assert r.status_code == 401


def test_no_coord_token_set_means_nothing_matches(services: Services, tokens: Tokens) -> None:
    services.tokens = Tokens(admin=tokens.admin, read=None, heartbeat=None)
    with TestClient(create_app(services)) as c:
        assert c.get("/api/health", headers=auth(tokens.coord)).status_code == 401

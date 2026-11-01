"""p3-09 PR 3: vigild posts a `vigil/verified` commit status on each task's `verified_sha`,
with a one-repo `statuses: write` token (owner, 2026-11-01; the ruleset requiring it on main
and the App's permission are the owner's ruling)."""

from __future__ import annotations

import json

import httpx2
import pytest

from vigild.github.app import ALLOWED, STATUS_PERMISSIONS
from vigild.github.publish import PublishError
from vigild.github.status import CONTEXT, post_verified

SHA = "a" * 40


def _client(status: int = 201) -> tuple[httpx2.Client, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(status, json={"state": "success"})

    return httpx2.Client(transport=httpx2.MockTransport(handler)), seen


def test_the_verified_status_is_success_on_the_exact_sha_with_its_context() -> None:
    http, seen = _client()
    post_verified(http, "tok", "o/r", SHA, main="b" * 40)
    (req,) = seen
    assert req.method == "POST" and req.url.path == f"/repos/o/r/statuses/{SHA}"
    body = json.loads(req.content)
    assert body["state"] == "success" and body["context"] == CONTEXT == "vigil/verified"
    assert "b" * 12 in body["description"]  # the main it was verified on
    assert req.headers["Authorization"] == "Bearer tok"


def test_a_bad_sha_is_refused_before_any_call() -> None:
    http, seen = _client()
    with pytest.raises(PublishError):
        post_verified(http, "tok", "o/r", "not-a-sha", main=SHA)
    assert seen == []


def test_a_refused_status_raises() -> None:
    http, _ = _client(status=403)
    with pytest.raises(PublishError, match="403"):
        post_verified(http, "tok", "o/r", SHA, main=SHA)


def test_statuses_write_is_mintable_and_only_on_its_own() -> None:
    assert dict(STATUS_PERMISSIONS) == {"statuses": "write"}
    assert ALLOWED["statuses"] == {"write"}

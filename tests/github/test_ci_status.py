"""vigild reads CI's `test` job for a commit (#191): a read-only, `checks: read` token,
and anything it can't read is `unknown`, never green."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from vigild.github.app import GitHubApp

REPO = "thomasbardhi01/vigil"
SHA = "a" * 40


def make_app(runs: Any, status: int = 200) -> tuple[GitHubApp, list[httpx2.Request]]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        p = req.url.path
        if p.endswith("/installation"):
            return httpx2.Response(200, json={"id": 1})
        if p.endswith("/access_tokens"):
            body = json.loads(req.content)
            return httpx2.Response(201, json={"token": "ghs_x", "permissions": body["permissions"]})
        if p == "/installation/token":
            return httpx2.Response(204)
        if p == f"/repos/{REPO}/commits/{SHA}/check-runs":
            return httpx2.Response(status, json={"check_runs": runs})
        return httpx2.Response(404)

    app = GitHubApp(
        "1",
        pem,
        http=httpx2.Client(transport=httpx2.MockTransport(handler)),
        claude_mods="thomasbardhi01/claude-mods",
        allowed_repos=[REPO],
    )
    return app, seen


def run(name: str, status: str, conclusion: str | None, id_: int = 1) -> dict[str, Any]:
    return {"id": id_, "name": name, "status": status, "conclusion": conclusion}


@pytest.mark.parametrize(
    ("runs", "want"),
    [
        ([run("lint", "completed", "failure"), run("test", "completed", "success")], "success"),
        ([run("test", "completed", "failure")], "failure"),
        ([run("test", "completed", "cancelled")], "failure"),
        ([run("test", "in_progress", None)], "pending"),
        ([run("lint", "completed", "success")], "pending"),  # no test run yet
        ([], "pending"),
        # a re-run: the newest run of the job decides
        (
            [run("test", "completed", "failure", 1), run("test", "completed", "success", 2)],
            "success",
        ),
        (
            [run("test", "completed", "success", 1), run("test", "completed", "failure", 2)],
            "failure",
        ),
    ],
)
def test_the_test_job_decides(runs: list[dict[str, Any]], want: str) -> None:
    app, seen = make_app(runs)
    assert app.ci_test_result(REPO, SHA) == want
    mint = next(r for r in seen if r.url.path.endswith("/access_tokens"))
    assert json.loads(mint.content)["permissions"] == {"checks": "read", "metadata": "read"}
    assert all(r.method in ("GET", "POST", "DELETE") for r in seen)


@pytest.mark.parametrize("status", [403, 404, 500])
def test_an_unreadable_answer_is_unknown(status: int) -> None:
    app, _ = make_app([run("test", "completed", "success")], status)
    assert app.ci_test_result(REPO, SHA) == "unknown"


def test_a_repo_that_cannot_be_minted_for_is_unknown() -> None:
    app, _ = make_app([])
    assert app.ci_test_result("o/not-listed", SHA) == "unknown"

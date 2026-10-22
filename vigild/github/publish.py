"""Publish a worker's branch: push it and open its draft PR, from the host.

P2 (owner, 2026-10-22): workers never hold a GitHub token. After a worker
session ends, vigild checks the branch is `vigil/*` and that every file it
changed is in the contract's scope (or the job's own `.vigil/` artifacts),
then pushes with a one-hour installation token and opens a draft PR. A
draft or nothing: there is no fallback to a ready-for-review PR.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import httpx2

from vigild.intake.paths import matches

BRANCH = re.compile(r"^vigil/[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9._-]+)*$")
PROTECTED = {"main", "master"}


class PublishError(RuntimeError):
    pass


class Pulls(Protocol):
    def create_pull(
        self, repo: str, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> str: ...


class RestPulls:
    """GitHub's REST API, authenticated with an installation token."""

    def __init__(
        self, http: httpx2.Client, token: str, api: str = "https://api.github.com"
    ) -> None:
        self.http = http
        self._token = token
        self.api = api.rstrip("/")

    def create_pull(
        self, repo: str, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> str:
        r = self.http.post(
            f"{self.api}/repos/{repo}/pulls",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
            timeout=30.0,
        )
        if r.status_code != 201:
            is_json = r.headers.get("content-type", "").startswith("application/json")
            msg = r.json().get("message", "") if is_json else r.text[:200]
            raise PublishError(f"{r.status_code}: {msg}")
        url: str = r.json()["html_url"]
        return url


def _git(cwd: Path, *args: str, token: str | None = None) -> str:
    env = dict(os.environ)
    if token:
        # The header reaches only this git process: never argv, never a file.
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.extraHeader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
    out = subprocess.run(
        ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=300, check=False
    )
    if out.returncode != 0:
        raise PublishError(f"git {args[0]} failed: {out.stderr.strip()[:300]}")
    return out.stdout.strip()


def out_of_scope(changed: Sequence[str], scope: Sequence[str]) -> list[str]:
    """Changed files that are neither in scope nor vigil's own artifacts."""
    return [
        f
        for f in changed
        if not f.startswith(".vigil/") and not any(f == s or matches(f, s) for s in scope)
    ]


def publish(
    clone: Path,
    *,
    repo: str,
    branch: str,
    base: str,
    title: str,
    body: str,
    pulls: Pulls,
    scope: Sequence[str],
    token: str | None = None,
) -> str:
    """Check, push `branch` to origin, and open a draft PR into `base`."""
    if branch in PROTECTED or branch == base or not BRANCH.match(branch) or ".." in branch:
        raise PublishError(f"refusing to publish branch {branch!r}: only vigil/* branches")
    head = _git(clone, "rev-parse", "--abbrev-ref", "HEAD")
    if head != branch:
        raise PublishError(f"{branch} is not checked out (HEAD is {head})")
    ahead = _git(clone, "rev-list", "--count", f"origin/{base}..HEAD")
    if int(ahead or 0) == 0:
        raise PublishError(f"{branch} has no commits ahead of {base}")
    changed = [
        f for f in _git(clone, "diff", "--name-only", f"origin/{base}...HEAD").splitlines() if f
    ]
    outside = out_of_scope(changed, scope)
    if outside:
        raise PublishError(f"files changed outside the contract's scope: {outside}")
    _git(clone, "push", "origin", f"HEAD:refs/heads/{branch}", token=token)
    return pulls.create_pull(repo, head=branch, base=base, title=title, body=body, draft=True)

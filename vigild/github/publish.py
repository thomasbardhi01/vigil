"""Push a worker's branch and open its draft PR: the one function for it.

Today (P2 undecided) this runs inside the worker container, called by the
executor's harness after the agent finishes, with a one-hour installation
token in a tmpfs file read by a git credential helper. If P2 is accepted,
vigild calls the same function from the host instead, and the container
holds no GitHub token at all. That is why this module imports nothing from
vigild: the image copies it as is.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Protocol

import httpx2

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
        self, http: httpx2.Client, token_file: Path, api: str = "https://api.github.com"
    ) -> None:
        self.http = http
        self.token_file = token_file
        self.api = api.rstrip("/")

    def create_pull(
        self, repo: str, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> str:
        token = self.token_file.read_text().strip()
        r = self.http.post(
            f"{self.api}/repos/{repo}/pulls",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": title, "head": head, "base": base, "body": body, "draft": draft},
            timeout=30.0,
        )
        if r.status_code != 201:
            msg = (
                r.json().get("message", "")
                if r.headers.get("content-type", "").startswith("application/json")
                else r.text[:200]
            )
            raise PublishError(f"{r.status_code}: {msg}")
        url: str = r.json()["html_url"]
        return url


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300, check=False
    )
    if out.returncode != 0:
        raise PublishError(f"git {args[0]} failed: {out.stderr.strip()[:300]}")
    return out.stdout.strip()


def publish(
    clone: Path, *, repo: str, branch: str, base: str, title: str, body: str, pulls: Pulls
) -> str:
    """Push `branch` to origin and open a draft PR into `base`. Returns its URL."""
    if branch in PROTECTED or branch == base or not BRANCH.match(branch) or ".." in branch:
        raise PublishError(f"refusing to publish branch {branch!r}: only vigil/* branches")
    head = _git(clone, "rev-parse", "--abbrev-ref", "HEAD")
    if head != branch:
        raise PublishError(f"{branch} is not checked out (HEAD is {head})")
    ahead = _git(clone, "rev-list", "--count", f"origin/{base}..HEAD")
    if int(ahead or 0) == 0:
        raise PublishError(f"{branch} has no commits ahead of {base}")
    _git(clone, "push", "origin", f"HEAD:refs/heads/{branch}")
    # A draft or nothing: never fall back to a ready-for-review PR.
    return pulls.create_pull(repo, head=branch, base=base, title=title, body=body, draft=True)

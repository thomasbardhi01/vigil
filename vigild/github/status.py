"""The `vigil/verified` commit status (p3-09 PR 3; owner, 2026-11-01).

vigild posts it on each task's `verified_sha`, the commit it rebased onto main, verified and
sent, with a one-repo `statuses: write` token (`STATUS_PERMISSIONS`). With the ruleset
requiring `vigil/verified` on main (the owner's ruling), GitHub itself refuses a merge whose
head vigild did not verify, beside vigild's own merge binding.
"""

from __future__ import annotations

import httpx2

from vigild.github.publish import PublishError
from vigild.workspace import SHA

CONTEXT = "vigil/verified"


def post_verified(
    http: httpx2.Client, token: str, repo: str, sha: str, *, main: str,
    api: str = "https://api.github.com",
) -> None:  # fmt: skip
    """`success` on `sha` under `vigil/verified`, naming the main it was verified on."""
    if not SHA.match(sha) or not SHA.match(main):
        raise PublishError("bad sha")
    r = http.post(
        f"{api.rstrip('/')}/repos/{repo}/statuses/{sha}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={
            "state": "success",
            "context": CONTEXT,
            "description": f"verified by vigild on main {main[:12]}",
        },
        timeout=30.0,
    )
    if r.status_code != 201:
        raise PublishError(f"posting {CONTEXT} on {repo}@{sha[:12]} failed (HTTP {r.status_code})")

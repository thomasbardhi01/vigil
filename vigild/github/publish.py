"""Publish a worker's branch: push it and open its draft PR, from the host.

P2 (owner, 2026-10-22): workers never hold a GitHub token. After a worker
session ends, vigild has imported its branch into the vault
(`Workspace.import_result`). Here it checks the branch is `vigil/*` and that
every file changed since the base commit vigild recorded (renames counted as
delete + add) is in the contract's scope or the job's own `.vigil/`
artifacts, then pushes the commit from the vault with a one-hour
installation token and opens a draft PR. A draft or nothing.

Tier 1 (owner, 2026-10-26): `.vigil/<job>/` stays in the vault. What goes out
is the checked tree without `.vigil/` (`Workspace.public_commit`), on the last
commit sent to the branch; the vault keeps the worker's full head. vigild only
fast-forwards: a branch sent before this (no record, `.vigil/` on it) is refused
(`LegacyBranch`) and left to the owner.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

import httpx2

from vigild.intake.paths import in_scope
from vigild.redact import redact

if TYPE_CHECKING:
    from vigild.workspace import Workspace

BRANCH = re.compile(r"^vigil/[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9._-]+)*$")
PROTECTED = {"main", "master"}


class PublishError(RuntimeError):
    pass


class LegacyBranch(PublishError):
    """The PR's branch predates artifact stripping: it is on the remote with
    `.vigil/` and vigild has no record of sending it. Only the owner can fix it."""


class BranchMoved(PublishError):
    """The remote tip of the branch is neither the commit vigild last sent nor an
    ancestor of the one it means to send: someone pushed to it. A retry would loop
    or overwrite their commit, so only a replan or an abandon is offered."""


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
            doc = r.json() if is_json else {}
            doc = doc if isinstance(doc, dict) else {}
            msg = doc.get("message", "") if is_json else r.text[:200]
            why = "; ".join(  # GitHub's own reason, e.g. "title is too long"
                str(e.get("message") or e.get("code") or "") if isinstance(e, dict) else str(e)
                for e in (doc.get("errors") or [])[:5]
            )
            if why:
                msg = f"{msg} ({why})"
            raise PublishError(redact(f"{r.status_code}: {msg}")[:600])
        url: str = r.json()["html_url"]
        return url

    def close(self, repo: str, number: int) -> None:
        """Close a PR vigild opened (a deps PR its review failed; owner, 2026-10-23)."""
        r = self.http.patch(
            f"{self.api}/repos/{repo}/pulls/{number}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"state": "closed"},
            timeout=30.0,
        )
        if r.status_code != 200:
            raise PublishError(f"closing {repo}#{number} failed (HTTP {r.status_code})")

    def update_pull(self, repo: str, url: str, *, title: str, body: str) -> None:
        """Rewrite a PR's title and body from the head vigild landed (#221)."""
        number = int(url.rstrip("/").rsplit("/", 1)[-1])
        r = self.http.patch(
            f"{self.api}/repos/{repo}/pulls/{number}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": redact(title), "body": redact(body)},
            timeout=30.0,
        )
        if r.status_code != 200:
            raise PublishError(f"updating {repo}#{number} failed (HTTP {r.status_code})")

    def head(self, repo: str, number: int) -> str:
        """A PR's head commit (the merge binding: it must be the verified SHA)."""
        r = self.http.get(
            f"{self.api}/repos/{repo}/pulls/{number}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        if r.status_code != 200:
            raise PublishError(f"reading {repo}#{number} failed (HTTP {r.status_code})")
        return str(r.json()["head"]["sha"])

    def state(self, repo: str, number: int) -> str:
        """A PR's state: open, merged or closed (vigild's PR poll, plan 2a item 5)."""
        r = self.http.get(
            f"{self.api}/repos/{repo}/pulls/{number}",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
        )
        if r.status_code != 200:
            raise PublishError(f"reading {repo}#{number} failed (HTTP {r.status_code})")
        doc = r.json()
        if doc.get("merged"):
            return "merged"
        return "closed" if doc.get("state") == "closed" else "open"


def artifact_paths(job_id: str, task_id: str) -> list[str]:
    """The only places under `.vigil/` a worker may write: its own task's
    folder and the task contract (#14 line 992). Its job's other paths, other
    tasks' folders and the playbook paths are out of scope like any file."""
    return [f".vigil/{job_id}/{task_id}/**", ".vigil/task.json"]


def vigild_paths(job_id: str) -> list[str]:
    """What vigild itself commits to a worker's branch before the session (the
    spec, plan and approval). They go in the PR; a worker's edit to one is
    refused by acceptance, which counts changes from after that commit."""
    return [f".vigil/{job_id}/{n}" for n in ("spec.md", "plan.md", "approval.json")]


def out_of_scope(changed: Sequence[str], scope: Sequence[str]) -> list[str]:
    """Changed files outside `scope`, which the caller extends with the task's
    own `artifact_paths`; there is no blanket exemption for `.vigil/`."""
    return [f for f in changed if not in_scope(f, scope)]


def publish(
    ws: Workspace,
    *,
    repo: str,
    head: str,
    base_sha: str,
    branch: str,
    base: str,
    title: str,
    body: str,
    pulls: Pulls,
    scope: Sequence[str],
    token: str | None = None,
    existing: str | None = None,
    push: bool = True,
    replace: str | None = None,
) -> str:
    """Check, push `head` to `branch`, and open a draft PR into `base`. `replace`
    (p3-09, a REWORK only; owner 2026-11-01) names `<task>/<n>`: the head was rebuilt on a
    new base, so the branch is replaced, not fast-forwarded, and only when its tip is what
    vigild itself last sent; that tip is first kept as `refs/vigil/rework/<task>/<n>`, and
    the open PR's title and body are rebuilt (#221). Every other publish only
    fast-forwards. With
    `existing` (a fix round on a published branch, phase 2a), the same checks
    and the push, and the PR that's already open stands. With `push=False` (a
    bench job's no-op publisher) the same checks run and the commit that would be
    sent is recorded in the vault, but nothing leaves the host."""
    from vigild.workspace import WorkspaceError

    if branch in PROTECTED or branch == base or not BRANCH.match(branch) or ".." in branch:
        raise PublishError(f"refusing to publish branch {branch!r}: only vigil/* branches")
    try:
        changed = [path for _, path in ws.changed(repo, base_sha, head)]
    except WorkspaceError as e:
        raise PublishError(str(e)) from e
    outside = out_of_scope(changed, scope)
    if outside:
        raise PublishError(f"files changed outside the contract's scope: {outside}")
    try:
        # Tier 1: the job's `.vigil/` artifacts stay in the vault; what goes to the
        # target repo is the same tree without them (the base's own `.vigil` kept)
        send = ws.public_commit(repo, head, base_sha, branch, fresh=replace is not None)
        if existing and ws.published_sha(repo, branch) is None and send != head and not replace:
            raise LegacyBranch(
                f"{branch} predates artifact stripping and carries .vigil/; vigild never "
                "forces a branch: the owner must clean it by hand, or re-plan"
            )
        sent = [path for _, path in ws.changed(repo, base_sha, send)]
        if not sent:
            raise PublishError(f"{branch} changes nothing since {base_sha[:12]}")
        outside = out_of_scope(sent, scope)  # what is sent, too
        if outside:
            raise PublishError(f"files in the commit sent are outside the scope: {outside}")
        if push and replace is not None:
            if not re.fullmatch(r"[A-Za-z0-9._-]+/[0-9]+", replace):
                raise PublishError(f"bad REWORK id {replace!r}")
            tip = ws.remote_tip(repo, branch, token)
            if tip is not None and tip != ws.published_sha(repo, branch):
                raise BranchMoved(
                    f"{branch} moved on the remote (tip {tip[:12]}): it is not what vigild "
                    "last sent, and a REWORK replaces only vigild's own send"
                )
            if tip is not None:  # the old tip is kept before anything replaces it
                ws._git(ws.vault(repo), "update-ref", f"refs/vigil/rework/{replace}", tip)
            try:
                ws.push(repo, send, branch, token, tip)
            except WorkspaceError as e:
                if "stale info" in str(e):
                    raise BranchMoved(
                        f"{branch} moved on the remote after vigild read it: nothing is overwritten"
                    ) from e
                raise
        elif push:
            tip = ws.remote_tip(repo, branch, token)
            if (
                tip is not None
                and tip != send
                and tip != ws.published_sha(repo, branch)
                and not ws.is_ancestor(repo, tip, send)
            ):
                raise BranchMoved(
                    f"{branch} moved on the remote (tip {tip[:12]}): it is not what vigild "
                    "last sent, and nothing is overwritten"
                )
            if tip is not None and tip != send and not ws.is_ancestor(repo, tip, send):
                raise PublishError(
                    f"{branch} would not fast-forward from the remote tip {tip[:12]}: "
                    "nothing is forced and nothing is pushed"
                )
            try:
                ws.push(repo, send, branch, token, tip)
            except WorkspaceError as e:
                # only a stale lease means the branch moved; a hook, ruleset or auth
                # refusal keeps its own cause (#198 review)
                if "stale info" in str(e):
                    seen = tip[:12] if tip else "no branch"
                    raise BranchMoved(
                        f"{branch} moved on the remote after vigild read it ({seen}): "
                        "nothing is overwritten"
                    ) from e
                raise
        ws.record_published(repo, branch, send)
    except WorkspaceError as e:
        raise PublishError(str(e)) from e
    if existing:
        update = getattr(pulls, "update_pull", None)
        if replace is not None and update is not None:  # #221: rebuilt from the new head
            update(repo, existing, title=redact(title), body=redact(body))
        return existing  # otherwise the open PR's title and body stand
    # the one redactor, for every caller: the title and body carry coord and worker text
    return pulls.create_pull(
        repo, head=branch, base=base, title=redact(title), body=redact(body), draft=True
    )

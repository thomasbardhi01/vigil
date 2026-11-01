"""Land a verified PR: rebase in the vault, re-verify the rebased head, bind the merge to it.

p3-09 (G1, pinned; #172, closes #221). vigild lands a job's PR itself. In the vault it
applies the task's change (base..head) onto the remote's current main with `git merge-tree`
(no work tree), runs the verifier on that rebased head, and pushes the commit it then sends,
recording it as the `verified_sha`. The owner's merge is accepted only when the PR head is
that SHA (`merge_allowed`).

- A conflict only in generated files takes main's side, runs the repo's generator once on
  the merged tree and retries; if main moves again and it still conflicts, it is REWORK.
- Any other conflict, or a red verdict, is REWORK: a fresh worker, never a model's merge.
- Before a ready card, a landed PR whose leased paths changed on main is stale
  (`is_stale`): it is landed again.

Every git call here goes through `Workspace._git` / `vigild.gitsafe`, in vigild's own
vault, never in a clone a session touched. Design: docs/plans/p3-09-landing.md.
"""

from __future__ import annotations

import shutil
import tempfile
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from vigild.github.publish import BRANCH, PROTECTED, BranchMoved, PublishError, out_of_scope
from vigild.gitsafe import GitError, git
from vigild.intake.paths import in_scope
from vigild.redact import redact
from vigild.workspace import VIGIL_DIR, Workspace, WorkspaceError

Verify = Callable[[str], bool]  # the verifier on a vault SHA: green or not
Regenerate = Callable[[Path, list[str]], None]  # the repo's generator, run on a checkout
RETRIES = 1  # a generated-only conflict is regenerated and retried once


class EditablePulls(Protocol):
    def create_pull(
        self, repo: str, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> str: ...

    def update_pull(self, repo: str, url: str, *, title: str, body: str) -> None: ...


@dataclass
class LandResult:
    outcome: Literal["landed", "rework"]
    verified_sha: str | None = None  # the commit sent: the only head a merge is accepted for
    vault_head: str | None = None  # the rebased head the verifier ran on
    main_sha: str | None = None  # the main it was rebased on and verified against
    conflicts: list[str] = field(default_factory=list)
    reason: str = ""
    pr_url: str | None = None


def merge_allowed(*, pr_head: str | None, verified_sha: str | None) -> bool:
    """The owner's merge is accepted only for the exact head vigild verified and sent."""
    return bool(verified_sha) and pr_head == verified_sha


class LandingQueue:
    """One lander per repo, first approved first; repos do not wait on each other."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiting: dict[str, list[tuple[str, str]]] = {}
        self._landing: dict[str, str] = {}

    def add(self, repo: str, task: str, *, approved_at: str) -> None:
        with self._lock:
            q = self._waiting.setdefault(repo, [])
            if task not in (t for _, t in q) and self._landing.get(repo) != task:
                q.append((approved_at, task))
                q.sort()

    def take(self, repo: str) -> str | None:
        with self._lock:
            q = self._waiting.get(repo)
            if repo in self._landing or not q:
                return None
            _, task = q.pop(0)
            self._landing[repo] = task
            return task

    def done(self, repo: str, task: str) -> None:
        with self._lock:
            if self._landing.get(repo) == task:
                del self._landing[repo]


# --- the vault side -------------------------------------------------------------------


def _main(ws: Workspace, repo: str) -> str:
    """The remote's main now, fetched into the vault (mirror, then vault)."""
    sha = ws.head_sha(repo, "main")
    ws._git(
        ws.vault(repo),
        "fetch",
        "--quiet",
        "--no-tags",
        str(ws._mirror_path(repo)),
        "+refs/heads/*:refs/mirror/*",
    )
    return sha


def _merge(ws: Workspace, repo: str, base_sha: str, main: str, head: str) -> tuple[str, list[str]]:
    """The task's change (base..head) applied onto `main`: the merged tree, and the paths
    that conflicted (the tree then carries conflict markers in them)."""
    # exit 0: clean; exit 1: conflicts, listed after the tree; anything else raises
    out = git(
        ws.vault(repo),
        "merge-tree",
        "--write-tree",
        "--name-only",
        "--no-messages",
        f"--merge-base={base_sha}",
        main,
        head,
        ok=(0, 1),
    )
    lines = [ln for ln in out.splitlines() if ln]
    return lines[0], sorted(set(lines[1:]))


def _with_main_side(ws: Workspace, repo: str, tree: str, main: str, paths: list[str]) -> str:
    """`tree` with each of `paths` replaced by main's version (a generated file)."""
    return _edit_tree(ws, repo, tree, {p: _blob(ws, repo, main, p) for p in paths})


def _blob(ws: Workspace, repo: str, sha: str, path: str) -> str | None:
    try:
        return ws._git(ws.vault(repo), "rev-parse", "--verify", "--quiet", f"{sha}:{path}")
    except WorkspaceError:
        return None


def _edit_tree(ws: Workspace, repo: str, tree: str, blobs: dict[str, str | None]) -> str:
    """`tree` with each path set to a blob (None removes it), through a scratch index."""
    vault = ws.vault(repo)
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(vault, "read-tree", tree, env=env)
        for path, blob in blobs.items():
            if blob is None:
                git(vault, "update-index", "--force-remove", "--", path, env=env)
            else:
                git(vault, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
        return git(vault, "write-tree", env=env)


def _regenerate(
    ws: Workspace, repo: str, tree: str, paths: list[str], regenerate: Regenerate
) -> str:
    """Run the repo's generator on a checkout of `tree` and write the generated files back."""
    vault = ws.vault(repo)
    with tempfile.TemporaryDirectory() as tmp:
        checkout = Path(tmp) / "tree"
        checkout.mkdir()
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index"), "GIT_WORK_TREE": str(checkout)}
        git(vault, "read-tree", tree, env=env)
        git(vault, "checkout-index", "--all", "--force", env=env)
        regenerate(checkout, list(paths))
        blobs = {}
        for p in paths:
            f = checkout / p
            blobs[p] = (
                git(vault, "hash-object", "-w", "--no-filters", "--", str(f))
                if f.is_file()
                else None
            )
        shutil.rmtree(checkout, ignore_errors=True)
    return _edit_tree(ws, repo, tree, blobs)


def _commit(ws: Workspace, repo: str, tree: str, parent: str, like: str) -> str:
    """A commit of `tree` on `parent`, with `like`'s author, committer and (redacted)
    message, so the same inputs give the same commit."""
    vault = ws.vault(repo)
    meta = ws._git(vault, "log", "-1", "--format=%an%x00%ae%x00%aI%x00%cn%x00%ce%x00%cI", like)
    an, ae, ad, cn, ce, cd = meta.split("\0")
    message = redact(git(vault, "log", "-1", "--format=%B", like, raw=True))
    env = {
        "GIT_AUTHOR_NAME": an,
        "GIT_AUTHOR_EMAIL": ae,
        "GIT_AUTHOR_DATE": ad,
        "GIT_COMMITTER_NAME": cn,
        "GIT_COMMITTER_EMAIL": ce,
        "GIT_COMMITTER_DATE": cd,
    }
    return git(vault, "commit-tree", tree, "-p", parent, stdin=message, env=env)


def _public_tree(ws: Workspace, repo: str, sha: str, main: str) -> str:
    """`sha`'s tree with the job's `.vigil/` replaced by main's (Tier 1)."""
    entries = [
        e
        for e in ws._git(ws.vault(repo), "ls-tree", "-z", sha).split("\0")
        if e and e.partition("\t")[2].lower() != VIGIL_DIR
    ] + ws._vigil_entries(repo, main)
    return git(ws.vault(repo), "mktree", "-z", "--missing", stdin="\0".join(entries) + "\0")


def _body(body: str, verified_sha: str, main: str) -> str:
    return (
        f"{body}\n\nLanded by vigild: verified on `{verified_sha[:12]}`, rebased on main "
        f"`{main[:12]}`. A merge is accepted only for this head."
    )


def land(
    ws: Workspace,
    *,
    repo: str,
    task_id: str,
    branch: str,
    head: str,
    base_sha: str,
    base: str,
    scope: Sequence[str],
    generated: Sequence[str],
    verify: Verify,
    regenerate: Regenerate,
    pulls: EditablePulls,
    title: str,
    body: str,
    existing: str | None,
    token: str | None,
) -> LandResult:
    """Rebase the task's head on the remote's main in the vault, verify the rebased head,
    send it with a lease and bind the merge to it. REWORK on a logic conflict, a red
    verdict, or a generated-file conflict that recurs after one regeneration."""
    if branch in PROTECTED or branch == base or not BRANCH.match(branch) or ".." in branch:
        raise PublishError(f"refusing to land branch {branch!r}: only vigil/* branches")
    try:
        for attempt in range(RETRIES + 1):
            main = _main(ws, repo)
            tree, conflicts = _merge(ws, repo, base_sha, main, head)
            if conflicts:
                logic = [c for c in conflicts if not in_scope(c, list(generated))]
                if logic:
                    return LandResult(
                        "rework",
                        main_sha=main,
                        conflicts=conflicts,
                        reason=f"conflict with main in {logic}",
                    )
                if attempt == RETRIES:
                    return LandResult(
                        "rework",
                        main_sha=main,
                        conflicts=conflicts,
                        reason="generated files still conflict after one retry",
                    )
                tree = _with_main_side(ws, repo, tree, main, conflicts)
                tree = _regenerate(ws, repo, tree, conflicts, regenerate)
                if _main(ws, repo) != main:
                    continue  # main moved while regenerating: the one retry
            rebased = _commit(ws, repo, tree, main, head)
            sent_paths = [p for _, p in ws.changed(repo, main, rebased)]
            outside = out_of_scope(
                [p for p in sent_paths if p.lower().split("/")[0] != VIGIL_DIR],
                [*scope, *generated],
            )
            if outside:
                return LandResult(
                    "rework",
                    main_sha=main,
                    vault_head=rebased,
                    reason=f"the rebased head changes files outside the scope: {outside}",
                )
            ws._git(ws.vault(repo), "update-ref", f"refs/vigil/{task_id}-landed", rebased)
            if not verify(rebased):
                return LandResult(
                    "rework",
                    main_sha=main,
                    vault_head=rebased,
                    reason="the verifier is red on the rebased head",
                )
            send = _commit(ws, repo, _public_tree(ws, repo, rebased, main), main, rebased)
            tip = ws.remote_tip(repo, branch, token)
            if tip is not None and tip != ws.published_sha(repo, branch):
                raise BranchMoved(
                    f"{branch} moved on the remote (tip {tip[:12]}): it is not what vigild "
                    "last sent, and nothing is overwritten"
                )
            ws.push(repo, send, branch, token, tip)
            ws.record_published(repo, branch, send)
            text = redact(_body(body, send, main))
            if existing:
                pulls.update_pull(repo, existing, title=redact(title), body=text)
                url = existing
            else:
                url = pulls.create_pull(
                    repo, head=branch, base=base, title=redact(title), body=text, draft=True
                )
            return LandResult(
                "landed", verified_sha=send, vault_head=rebased, main_sha=main, pr_url=url
            )
    except (GitError, WorkspaceError) as e:
        raise PublishError(str(e)) from e
    raise AssertionError("unreachable")  # pragma: no cover


def is_stale(
    ws: Workspace, *, repo: str, verified_on: str | None, scope: Sequence[str], token: str | None
) -> bool:
    """A landed PR is stale when main changed a path its task leases (today its scope
    globs; p3-05's leases later) since the main it was verified on."""
    if not verified_on:
        return True
    main = _main(ws, repo)
    if main == verified_on:
        return False
    return any(in_scope(p, list(scope)) for _, p in ws.changed(repo, verified_on, main))

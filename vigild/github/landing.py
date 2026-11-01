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
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from vigild.github.publish import BRANCH, PROTECTED, BranchMoved, PublishError, out_of_scope
from vigild.gitsafe import GitError, git, git_rc
from vigild.intake.paths import in_scope
from vigild.redact import redact
from vigild.workspace import SHA, VIGIL_DIR, Workspace, WorkspaceError

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
    # why it is not landed: logic_conflict, generated_conflict, outside_scope,
    # red_on_rebased or already_on_main
    cause: str = ""


def merge_allowed(*, pr_head: str | None, verified_sha: str | None) -> bool:
    """The owner's merge is accepted only for the exact head vigild verified and sent."""
    return bool(verified_sha) and pr_head == verified_sha


class LandingQueue:
    """One lander per repo, first approved first; repos do not wait on each other."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turn = threading.Condition(self._lock)
        self._waiting: dict[str, list[tuple[datetime, str]]] = {}
        self._landing: dict[str, str] = {}
        self._holder: dict[str, int] = {}  # the thread that holds each repo's slot

    @contextmanager
    def hold(self, repo: str, task: str, *, approved_at: str) -> Iterator[None]:
        """Land `task` holding `repo`'s one landing slot (p3-09 PR 3): wait while another
        lander holds it; among the waiters, the earliest approved goes next. The slot is let
        go however the landing ends."""
        with self._turn:
            if self._landing.get(repo) == task and self._holder.get(repo) == threading.get_ident():
                raise RuntimeError(f"{task} already holds {repo}'s landing slot")
        self.add(repo, task, approved_at=approved_at)
        with self._turn:
            while True:
                q = self._waiting.get(repo) or []
                if repo not in self._landing and q and q[0][1] == task:
                    break
                if repo not in self._landing and not any(t == task for _, t in q):
                    # another caller for this job took its entry and has let go: queue again
                    self._add(repo, task, approved_at)
                    continue
                self._turn.wait()
            self._waiting[repo].pop(0)
            self._landing[repo] = task
            self._holder[repo] = threading.get_ident()
        try:
            yield
        finally:
            self.done(repo, task)

    def add(self, repo: str, task: str, *, approved_at: str) -> None:
        with self._lock:
            self._add(repo, task, approved_at)

    def _add(self, repo: str, task: str, approved_at: str) -> None:
        """Called with the lock held."""
        q = self._waiting.setdefault(repo, [])
        if task not in (t for _, t in q) and self._landing.get(repo) != task:
            q.append((datetime.fromisoformat(approved_at), task))
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
                self._holder.pop(repo, None)
            self._turn.notify_all()


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
    # exit 0: clean; exit 1: conflicts, listed after the tree, NUL-separated (names are
    # never quoted); anything else raises
    rc, out = git_rc(
        ws.vault(repo), "merge-tree", "--write-tree", "--name-only", "--no-messages", "-z",
        f"--merge-base={base_sha}", main, head, ok=(0, 1), raw=True,
    )  # fmt: skip
    fields = [f for f in out.split("\0") if f]
    if not fields or not SHA.match(fields[0].strip()):
        raise WorkspaceError("merge-tree gave no tree")
    tree, conflicts = fields[0].strip(), sorted(set(fields[1:]))
    if (rc == 1) != bool(conflicts):
        raise WorkspaceError(f"merge-tree exit {rc} disagrees with its conflict list")
    return tree, conflicts


def _with_main_side(ws: Workspace, repo: str, tree: str, main: str, paths: list[str]) -> str:
    """`tree` with each of `paths` replaced by main's version (a generated file)."""
    return _edit_tree(ws, repo, tree, {p: _blob(ws, repo, main, p) for p in paths})


def _blob(ws: Workspace, repo: str, sha: str, path: str) -> tuple[str, str] | None:
    """(mode, blob) of a regular file at `path` in `sha`, or None if there is none; a
    directory, symlink or submodule there is refused, never written as a file."""
    out = ws._git(ws.vault(repo), "ls-tree", "-z", sha, "--", path)
    entry = out.split("\0")[0]
    if not entry:
        return None
    meta, _, _ = entry.partition("\t")
    mode, kind, oid = meta.split(" ")
    if kind != "blob" or mode not in ("100644", "100755"):
        raise WorkspaceError(f"generated path {path!r} is not a regular file on main ({mode})")
    return mode, oid


def _edit_tree(
    ws: Workspace, repo: str, tree: str, blobs: dict[str, tuple[str, str] | None]
) -> str:
    """`tree` with each path set to (mode, blob) (None removes it), through a scratch index."""
    vault = ws.vault(repo)
    with tempfile.TemporaryDirectory() as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(vault, "read-tree", tree, env=env)
        for path, entry in blobs.items():
            if entry is None:
                git(vault, "update-index", "--force-remove", "--", path, env=env)
            else:
                mode, oid = entry
                git(vault, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}", env=env)
        return git(vault, "write-tree", env=env)


def _regenerate(
    ws: Workspace, repo: str, tree: str, paths: list[str], regenerate: Regenerate
) -> str:
    """Run the repo's generator on a checkout of `tree` and write the generated files back."""
    vault = ws.vault(repo)
    links = [
        e.partition("\t")[2]
        for e in git(vault, "ls-tree", "-r", "-z", tree).split("\0")
        if e.startswith(("120000 ", "160000 "))
    ]
    if links:  # a worker's symlink must never lead the generator off the checkout
        raise WorkspaceError(f"refusing to regenerate over symlinks or submodules: {links[:5]}")
    with tempfile.TemporaryDirectory() as tmp:
        checkout = Path(tmp) / "tree"
        checkout.mkdir()
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index"), "GIT_WORK_TREE": str(checkout)}
        git(vault, "read-tree", tree, env=env)
        git(vault, "checkout-index", "--all", "--force", env=env)
        regenerate(checkout, list(paths))
        blobs: dict[str, tuple[str, str] | None] = {}
        for p in paths:
            f = checkout / p
            if f.is_symlink() or (f.exists() and not f.is_file()):
                raise WorkspaceError(f"the generator left {p!r} as something other than a file")
            blobs[p] = (
                ("100644", git(vault, "hash-object", "-w", "--no-filters", "--", str(f)))
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
                        cause="logic_conflict",
                    )
                if attempt == RETRIES:
                    return LandResult(
                        "rework",
                        main_sha=main,
                        conflicts=conflicts,
                        reason="generated files still conflict after one retry",
                        cause="generated_conflict",
                    )
                tree = _with_main_side(ws, repo, tree, main, conflicts)
                tree = _regenerate(ws, repo, tree, conflicts, regenerate)
                if _main(ws, repo) != main:
                    continue  # main moved while regenerating: the one retry
            rebased = _commit(ws, repo, tree, main, head)
            sent_paths = [p for _, p in ws.changed(repo, main, rebased)]
            if not [p for p in sent_paths if p.lower().split("/")[0] != VIGIL_DIR]:
                return LandResult(
                    "rework", main_sha=main, vault_head=rebased,
                    reason="the change is already on main: landing it changes nothing",
                    cause="already_on_main",
                )  # fmt: skip
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
                    conflicts=outside,
                    cause="outside_scope",
                )
            ws._git(ws.vault(repo), "update-ref", f"refs/vigil/{task_id}-landed", rebased)
            if not verify(rebased):
                return LandResult(
                    "rework",
                    main_sha=main,
                    vault_head=rebased,
                    reason="the verifier is red on the rebased head",
                    cause="red_on_rebased",
                )
            send = _commit(ws, repo, _public_tree(ws, repo, rebased, main), main, rebased)
            tip = ws.remote_tip(repo, branch, token)
            if tip is not None and tip != ws.published_sha(repo, branch):
                raise BranchMoved(
                    f"{branch} moved on the remote (tip {tip[:12]}): it is not what vigild "
                    "last sent, and nothing is overwritten"
                )
            try:
                ws.push(repo, send, branch, token, tip)
            except WorkspaceError as e:
                if "stale info" in str(e):  # the branch moved after vigild read it
                    seen = tip[:12] if tip else "no branch"
                    raise BranchMoved(
                        f"{branch} moved on the remote after vigild read it ({seen}): "
                        "nothing is overwritten"
                    ) from e
                raise
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
    ws: Workspace,
    *,
    repo: str,
    verified_on: str | None,
    scope: Sequence[str],
    token: str | None,
    generated: Sequence[str] = (),
) -> bool:
    """A landed PR is stale when main changed a path its task leases (today its scope
    globs; p3-05's leases later), or a generated file it regenerated, since the main it
    was verified on."""
    if not verified_on:
        return True
    main = _main(ws, repo)
    if main == verified_on:
        return False
    paths = [*scope, *generated]
    return any(in_scope(p, paths) for _, p in ws.changed(repo, verified_on, main))

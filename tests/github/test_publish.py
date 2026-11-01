"""vigild publishes from the host (P2), from its vault: checks, push, draft PR.
Workers hold no token. Rename, base-ref and hostile-.git cases are in
tests/test_vault.py."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import git
from tests.harness import finish_session
from vigild.github.publish import PublishError, artifact_paths, publish
from vigild.workspace import Workspace

REPO, TID, BRANCH = "o/fixture", "fx-0001-w1", "vigil/fx-0001-w1-doc"


@dataclass
class FakePulls:
    bare: Path
    prs: list[dict[str, Any]] = field(default_factory=list)
    refuse_draft: bool = False

    def create_pull(
        self, repo: str, *, head: str, base: str, title: str, body: str, draft: bool
    ) -> str:
        if self.refuse_draft:
            raise PublishError("422: Draft pull requests are not supported in this repository.")
        git(self.bare, "rev-parse", "--verify", f"refs/heads/{head}")  # GitHub checks too
        self.prs.append({"head": head, "base": base, "draft": draft, "title": title, "body": body})
        return f"https://github.com/{repo}/pull/{len(self.prs)}"


@pytest.fixture
def setup(tmp_path: Path, fixture_repo: dict[str, Path]) -> tuple[Workspace, str, str, Path]:
    ws = Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"]))
    clone = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    (clone / "docs" / "feature-map.md").write_text("# Feature map\nrate limit\n")
    r = finish_session(clone, tmp_path / "out", branch=BRANCH, base_sha=base)
    head = ws.import_result(REPO, TID, tmp_path / "out", BRANCH, base, head=r["head"])
    return ws, base, head, fixture_repo["bare"]


def _pub(ws: Workspace, base: str, head: str, pulls: FakePulls, branch: str = BRANCH) -> str:
    return publish(
        ws,
        repo=REPO,
        head=head,
        base_sha=base,
        branch=branch,
        base="main",
        title="t",
        body="b",
        pulls=pulls,
        scope=["docs/feature-map.md"],
    )


def test_publish_pushes_the_branch_and_opens_a_draft(
    setup: tuple[Workspace, str, str, Path],
) -> None:
    ws, base, head, bare = setup
    pulls = FakePulls(bare)
    assert _pub(ws, base, head, pulls) == "https://github.com/o/fixture/pull/1"
    assert pulls.prs[0]["draft"] is True and pulls.prs[0]["base"] == "main"
    assert git(bare, "rev-parse", f"refs/heads/{BRANCH}") == head
    assert git(bare, "log", "-1", "--format=%s", "main") == "seed"


@pytest.mark.parametrize("branch", ["main", "master", "feature/x", "vigil/../main"])
def test_publish_refuses_anything_but_a_vigil_branch(
    setup: tuple[Workspace, str, str, Path], branch: str
) -> None:
    ws, base, head, bare = setup
    with pytest.raises(PublishError):
        _pub(ws, base, head, FakePulls(bare), branch=branch)


def test_publish_never_falls_back_to_a_non_draft(setup: tuple[Workspace, str, str, Path]) -> None:
    ws, base, head, bare = setup
    pulls = FakePulls(bare, refuse_draft=True)
    with pytest.raises(PublishError, match="Draft"):
        _pub(ws, base, head, pulls)
    assert pulls.prs == []


def test_publish_with_nothing_changed_fails(setup: tuple[Workspace, str, str, Path]) -> None:
    ws, base, _, bare = setup
    with pytest.raises(PublishError, match="changes nothing"):
        _pub(ws, base, base, FakePulls(bare))


def test_publish_refuses_files_outside_the_scope(
    tmp_path: Path, fixture_repo: dict[str, Path]
) -> None:
    ws = Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"]))
    clone = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    (clone / "docs" / "feature-map.md").write_text("ok\n")
    (clone / "README.md").write_text("sneaky\n")
    r = finish_session(clone, tmp_path / "out", branch=BRANCH, base_sha=base)
    head = ws.import_result(REPO, TID, tmp_path / "out", BRANCH, base, head=r["head"])
    pulls = FakePulls(fixture_repo["bare"])
    with pytest.raises(PublishError, match=r"README\.md"):
        _pub(ws, base, head, pulls)
    with pytest.raises(subprocess.CalledProcessError):  # nothing was pushed
        git(fixture_repo["bare"], "rev-parse", "--verify", f"refs/heads/{BRANCH}")
    assert pulls.prs == []


def _artifact_pub(
    tmp_path: Path, fixture_repo: dict[str, Path], files: list[str]
) -> tuple[Workspace, str, str]:
    ws = Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"]))
    clone = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    for f in files:
        (clone / f).parent.mkdir(parents=True, exist_ok=True)
        (clone / f).write_text("{}")
    (clone / "docs" / "feature-map.md").write_text("ok\n")
    r = finish_session(clone, tmp_path / "out", branch=BRANCH, base_sha=base)
    head = ws.import_result(REPO, TID, tmp_path / "out", BRANCH, base, head=r["head"])
    return ws, base, head


def _scoped(ws: Workspace, base: str, head: str, pulls: FakePulls) -> str:
    return publish(
        ws, repo=REPO, head=head, base_sha=base, branch=BRANCH, base="main", title="t", body="b",
        pulls=pulls,
        scope=["docs/feature-map.md", *artifact_paths("fx-0001", TID)],
    )  # fmt: skip


def test_a_worker_may_write_only_its_own_task_folder_and_task_json(
    tmp_path: Path, fixture_repo: dict[str, Path]
) -> None:
    ws, base, head = _artifact_pub(
        tmp_path,
        fixture_repo,
        [".vigil/fx-0001/fx-0001-w1/worker_report.json", ".vigil/task.json"],
    )
    assert _scoped(ws, base, head, FakePulls(fixture_repo["bare"])).endswith("/pull/1")


@pytest.mark.parametrize(
    "path",
    [
        ".vigil/fx-0001/spec.md",  # its own job's other paths
        ".vigil/fx-0001/fx-0001-w2/worker_report.json",  # another task's folder
        ".vigil/fx-0002/fx-0002-w1/worker_report.json",  # another job
        ".vigil/fx-0001/hidden/fx-0001-w1/test_x.py",  # where hidden tests live
        ".vigil/fx-0001/hidden/pytest.ini",
        ".vigil/playbook/rules.md",  # the playbook paths
        ".vigil/other.json",
    ],
)
def test_any_other_vigil_path_is_out_of_scope(
    tmp_path: Path, fixture_repo: dict[str, Path], path: str
) -> None:
    ws, base, head = _artifact_pub(tmp_path, fixture_repo, [path])
    pulls = FakePulls(fixture_repo["bare"])
    with pytest.raises(PublishError, match="outside the contract's scope"):
        _scoped(ws, base, head, pulls)
    assert pulls.prs == []


def test_the_pr_poll_reads_a_prs_state() -> None:
    """Plan 2a, item 5: merged, closed or open, from GitHub's pulls API."""
    import httpx2

    from vigild.github.publish import RestPulls

    answers = {"1": {"merged": True, "state": "closed"}, "2": {"merged": False, "state": "closed"},
               "3": {"merged": False, "state": "open"}}  # fmt: skip

    def handler(req: httpx2.Request) -> httpx2.Response:
        assert req.headers["authorization"] == "Bearer ghs_read"
        return httpx2.Response(200, json=answers[req.url.path.rsplit("/", 1)[1]])

    pulls = RestPulls(httpx2.Client(transport=httpx2.MockTransport(handler)), "ghs_read")
    assert [pulls.state("o/x", n) for n in (1, 2, 3)] == ["merged", "closed", "open"]


def test_the_pr_poll_reads_only_the_repos_own_prs() -> None:
    import pytest

    from vigild.github.publish import PublishError
    from vigild.jobs.runner import GitHubPRs

    with pytest.raises(PublishError):
        GitHubPRs(app=None).state("o/x", "https://github.com/o/other/pull/1")


def test_closing_a_pr_patches_its_state_with_a_one_repo_write_token() -> None:
    """Owner ruling 3: vigild closes a deps PR whose review failed."""
    import json

    import httpx2

    from vigild.github.app import InstallationToken
    from vigild.github.publish import PublishError
    from vigild.jobs.runner import GitHubPublisher

    seen: list[httpx2.Request] = []

    def handler(req: httpx2.Request) -> httpx2.Response:
        seen.append(req)
        return httpx2.Response(200, json={"state": "closed"})

    leased: list[tuple[str, dict[str, str]]] = []

    class App:
        from contextlib import contextmanager

        @contextmanager
        def lease(self, repo: str, perms: dict[str, str], job_id: str | None = None):  # type: ignore[no-untyped-def]
            leased.append((repo, perms))
            yield InstallationToken(repo, perms, "z", "ghs_w")

    pub = GitHubPublisher(App(), httpx2.Client(transport=httpx2.MockTransport(handler)), None)  # type: ignore[arg-type]
    pub.close("o/fixture", "https://github.com/o/fixture/pull/7")
    (req,) = seen
    assert req.method == "PATCH" and req.url.path == "/repos/o/fixture/pulls/7"
    assert json.loads(req.content) == {"state": "closed"}
    assert leased == [("o/fixture", {"pull_requests": "write"})]
    try:
        pub.close("o/fixture", "https://github.com/other/repo/pull/7")
    except PublishError:
        pass
    else:
        raise AssertionError("a PR of another repo was closed")


def test_a_branch_that_moved_on_the_remote_is_refused_before_any_push_or_record(
    setup: tuple[Workspace, str, str, Path],
) -> None:
    """#32: the remote tip is neither vigild's record nor behind the commit sent."""
    ws, base, head, bare = setup
    tree = git(bare, "rev-parse", f"{base}^{{tree}}")
    outside = git(bare, "-c", "user.name=t", "-c", "user.email=t@t", "commit-tree", tree,
                  "-p", base, "-m", "someone else's push")  # fmt: skip
    git(bare, "update-ref", f"refs/heads/{BRANCH}", outside)
    pulls = FakePulls(bare)
    with pytest.raises(PublishError) as raised:
        _pub(ws, base, head, pulls)
    assert type(raised.value).__name__ == "BranchMoved"
    assert "moved on the remote" in str(raised.value)
    assert git(bare, "rev-parse", f"refs/heads/{BRANCH}") == outside  # not overwritten
    assert ws.published_sha(REPO, BRANCH) is None  # no record written
    assert pulls.prs == []


def _other_commit(bare: Path, parent: str, msg: str) -> str:
    tree = git(bare, "rev-parse", f"{parent}^{{tree}}")
    return git(bare, "-c", "user.name=t", "-c", "user.email=t@t", "commit-tree", tree,
               "-p", parent, "-m", msg)  # fmt: skip


def test_a_push_after_the_tip_read_is_atomic_against_that_tip(
    setup: tuple[Workspace, str, str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#198: something lands between `remote_tip` and the push: BranchMoved, no overwrite."""
    ws, base, head, bare = setup
    real = ws.remote_tip
    landed: list[str] = []

    def racing(repo: str, branch: str, token: str | None) -> str | None:
        tip = real(repo, branch, token)
        landed.append(_other_commit(bare, base, "lands in the gap"))
        git(bare, "update-ref", f"refs/heads/{BRANCH}", landed[0])
        return tip

    monkeypatch.setattr(ws, "remote_tip", racing)
    pulls = FakePulls(bare)
    with pytest.raises(PublishError) as raised:
        _pub(ws, base, head, pulls)
    assert type(raised.value).__name__ == "BranchMoved"
    assert git(bare, "rev-parse", f"refs/heads/{BRANCH}") == landed[0]  # not overwritten
    assert ws.published_sha(REPO, BRANCH) is None and pulls.prs == []


def test_the_push_carries_a_lease_on_the_checked_tip(
    setup: tuple[Workspace, str, str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    ws, base, head, bare = setup
    calls: list[tuple[str, ...]] = []
    real = ws._git

    def spy(cwd: Path, *args: str, token: str | None = None) -> str:
        if args[0] == "push":
            calls.append(args)
        return real(cwd, *args, token=token)

    monkeypatch.setattr(ws, "_git", spy)
    pulls = FakePulls(bare)
    _pub(ws, base, head, pulls)  # first publish: the branch must not exist
    assert f"--force-with-lease=refs/heads/{BRANCH}:" in calls[0]
    first = git(bare, "rev-parse", f"refs/heads/{BRANCH}")
    vault = ws.vault(REPO)
    from vigild.gitsafe import git as safe_git

    idx = {"GIT_INDEX_FILE": str(ws.data_dir / "t198.idx")}
    safe_git(vault, "read-tree", head, env=idx)
    blob = safe_git(vault, "hash-object", "-w", "--stdin", stdin="# Feature map\nrate limit 2\n")
    safe_git(vault, "update-index", "--cacheinfo", f"100644,{blob},docs/feature-map.md", env=idx)
    tree = safe_git(vault, "write-tree", env=idx)
    head2 = git(vault, "-c", "user.name=t", "-c", "user.email=t@t", "commit-tree", tree,
                "-p", head, "-m", "second")  # fmt: skip
    git(vault, "update-ref", "refs/vigil/second", head2)
    _pub(ws, base, head2, pulls)  # fast-forwards the tip it checked
    second = git(bare, "rev-parse", f"refs/heads/{BRANCH}")
    assert second != first and git(bare, "merge-base", "--is-ancestor", first, second) == ""
    assert f"--force-with-lease=refs/heads/{BRANCH}:{first}" in calls[1]


def test_a_protected_branch_rejection_is_not_branch_moved(
    setup: tuple[Workspace, str, str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#198 review: only a stale lease is BranchMoved; a ruleset or hook refusal keeps its cause."""
    from vigild.workspace import WorkspaceError

    ws, base, head, _bare = setup

    def refuse(*a: object, **k: object) -> None:
        raise WorkspaceError(
            "git push failed: ! [remote rejected] HEAD -> vigil/x (protected branch hook declined)"
        )

    monkeypatch.setattr(ws, "push", refuse)
    with pytest.raises(PublishError) as raised:
        _pub(ws, base, head, FakePulls(_bare))
    assert type(raised.value).__name__ != "BranchMoved"
    assert "protected branch" in str(raised.value)


def test_a_non_fast_forward_is_refused_and_nothing_is_pushed(
    setup: tuple[Workspace, str, str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """#198: the lease would allow it when the tip matches; vigild never forces."""
    ws, base, head, bare = setup
    outside = _other_commit(bare, base, "recorded publish")
    git(ws.vault(REPO), "fetch", "--quiet", str(bare), outside)
    git(bare, "update-ref", f"refs/heads/{BRANCH}", outside)
    ws.record_published(REPO, BRANCH, outside)
    monkeypatch.setattr(ws, "public_commit", lambda *a, **k: head)  # head does not descend
    pulls = FakePulls(bare)
    with pytest.raises(PublishError) as raised:
        _pub(ws, base, head, pulls)
    assert type(raised.value).__name__ != "BranchMoved"
    assert BRANCH in str(raised.value) and "forced" in str(raised.value)
    assert git(bare, "rev-parse", f"refs/heads/{BRANCH}") == outside
    assert pulls.prs == []


# fake token shapes, assembled so no whole one sits in the source
SECRETS = {
    "sk": "sk-" + "A1b2C3d4E5f6",
    "ghs": "ghs_" + "A1b2C3d4E5f6",
    "vgw": "vgw_" + "A1b2C3d4E5f6",
    "pem": "-----BEGIN "
    + "PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0B\n-----END "
    + "PRIVATE KEY-----",
}


@pytest.mark.parametrize("kind", sorted(SECRETS))
def test_publish_redacts_the_title_and_body_whatever_the_caller_built(
    setup: tuple[Workspace, str, str, Path], kind: str
) -> None:
    ws, base, head, bare = setup
    pulls = FakePulls(bare)
    publish(
        ws,
        repo=REPO,
        head=head,
        base_sha=base,
        branch=BRANCH,
        base="main",
        title=f"[vigil x] fix {SECRETS[kind]} leak",
        body=f"summary quoting {SECRETS[kind]} from a log\n\nOpened by vigild",
        pulls=pulls,
        scope=["docs/feature-map.md"],
    )
    (pr,) = pulls.prs
    assert "[redacted]" in pr["title"] and "[redacted]" in pr["body"]
    for out in (pr["title"], pr["body"]):
        assert "A1b2C3d4E5f6" not in out and "MIIEvQ" not in out and "PRIVATE KEY" not in out
    assert pr["body"].endswith("\n\nOpened by vigild")


def test_an_ordinary_title_and_body_are_published_unchanged(
    setup: tuple[Workspace, str, str, Path],
) -> None:
    ws, base, head, bare = setup
    pulls = FakePulls(bare)
    title, body = "[vigil x] add a row", "Closes #3\n\nTest: `pytest -q` fail → pass."
    publish(
        ws, repo=REPO, head=head, base_sha=base, branch=BRANCH, base="main",
        title=title, body=body, pulls=pulls, scope=["docs/feature-map.md"],
    )  # fmt: skip
    assert (pulls.prs[0]["title"], pulls.prs[0]["body"]) == (title, body)


def test_the_public_commit_message_is_redacted_and_deterministic(
    tmp_path: Path, fixture_repo: dict[str, Path]
) -> None:
    ws = Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"]))
    clone = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    (clone / "docs" / "feature-map.md").write_text("# Feature map\nrate limit\n")
    git(clone, "add", "-A")
    msg = f"quote {SECRETS['sk']}\n\n{SECRETS['pem']}\n\nend"
    git(clone, "-c", "user.name=w", "-c", "user.email=w@x", "commit", "-q", "-m", msg)
    r = finish_session(clone, tmp_path / "out", branch=BRANCH, base_sha=base)
    head = ws.import_result(REPO, TID, tmp_path / "out", BRANCH, base, head=r["head"])
    a = ws.public_commit(REPO, head, base, BRANCH)
    b = ws.public_commit(REPO, head, base, BRANCH)
    assert a == b
    shown = git(ws.vault(REPO), "log", "-1", "--format=%B", a)
    assert "[redacted]" in shown and "A1b2C3d4E5f6" not in shown and "MIIEvQ" not in shown
    assert shown.rstrip().endswith("end")


def test_an_earlier_commit_message_with_a_secret_is_never_published(
    tmp_path: Path, fixture_repo: dict[str, Path]
) -> None:
    """Review of #249: a branch whose head message is clean but an EARLIER commit's
    message holds a key must not be passed through with its history; every message
    sent to GitHub is redacted."""
    ws = Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"]))
    clone = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    who = ("-c", "user.name=w", "-c", "user.email=w@x")
    (clone / "docs" / "feature-map.md").write_text("# Feature map\nfirst\n")
    git(clone, "add", "-A")
    git(clone, *who, "commit", "-q", "-m", f"wip {SECRETS['sk']}")
    (clone / "docs" / "feature-map.md").write_text("# Feature map\nsecond\n")
    git(clone, "add", "-A")
    git(clone, *who, "commit", "-q", "-m", "clean message")
    r = finish_session(clone, tmp_path / "out", branch=BRANCH, base_sha=base)
    head = ws.import_result(REPO, TID, tmp_path / "out", BRANCH, base, head=r["head"])
    sent = ws.public_commit(REPO, head, base, BRANCH)
    history = git(ws.vault(REPO), "log", "--format=%B", f"{base}..{sent}")
    assert "A1b2C3d4E5f6" not in history


# --- p3-09: landing queue and rebase-on-land (#172, closes #221) -----------------------
#
# Failing tests first (owner, 2026-11-01): they pin `vigild.github.landing`, which does not
# exist yet. vigild lands a verified PR itself: in the vault it rebases the `vigil/*` branch
# on the remote's current main, runs the verifier on the rebased head, records the commit
# it then sends as `verified_sha`, and pushes it with a lease. A merge is accepted only
# when the PR head is that SHA. A conflict in a generated file is regenerated and retried
# once; any other conflict, or a red verdict, is REWORK (a fresh worker), never resolved
# by a model. The design is in docs/plans/p3-09-landing.md.

GEN = "docs/feature-map.md"


def _landing() -> Any:
    import importlib

    return importlib.import_module("vigild.github.landing")


def _main_commit(seed: Path, bare: Path, path: str, text: str, msg: str) -> str:
    """Someone else's PR lands on main: commit on the seed clone, push to the remote."""
    git(seed, "pull", "-q", "--ff-only", "origin", "main")
    (seed / path).write_text(text)
    git(seed, "add", path)
    git(seed, "commit", "-q", "-m", msg)
    git(seed, "push", "-q", "origin", "main")
    return git(seed, "rev-parse", "HEAD")


@dataclass
class Verifier:
    """Stands in for `vigild/verifier.py`: records every SHA it ran on and answers green
    unless told otherwise."""

    green: bool = True
    ran: list[str] = field(default_factory=list)

    def __call__(self, sha: str) -> bool:
        self.ran.append(sha)
        return self.green


@dataclass
class Regen:
    """Stands in for the generator (`scripts/gen-docs-tables.py`): rewrites the generated
    files in the checkout it is handed, and counts its runs."""

    text: str = "# Feature map\nrate limit\nmain's row\n"
    runs: int = 0

    def __call__(self, checkout: Path, paths: list[str]) -> None:
        self.runs += 1
        for p in paths:
            (checkout / p).write_text(self.text)


@dataclass
class EditablePulls(FakePulls):
    """A PR that already exists: `update_pull` rewrites its title and body (#221)."""

    updates: list[dict[str, Any]] = field(default_factory=list)

    def update_pull(self, repo: str, url: str, *, title: str, body: str) -> None:
        self.updates.append({"url": url, "title": title, "body": body})


def _land(
    ws: Workspace, base: str, head: str, pulls: FakePulls, verify: Verifier,
    *, generated: list[str] | None = None, regen: Regen | None = None,
    existing: str | None = None, body: str = "b",
) -> Any:  # fmt: skip
    return _landing().land(
        ws, repo=REPO, task_id=TID, branch=BRANCH, head=head, base_sha=base, base="main",
        scope=["docs/feature-map.md"], generated=generated or [], verify=verify,
        regenerate=regen or Regen(), pulls=pulls, title="t", body=body, existing=existing,
        token=None,
    )  # fmt: skip


def test_rebase_reverify_lands_the_rebased_head_and_records_its_sha(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path]
) -> None:
    """Main moved (an unrelated file): the branch is rebased on it in the vault, the
    verifier runs on the rebased head, not the worker's, and the commit pushed is the one
    recorded as `verified_sha`, a descendant of the new main."""
    ws, base, head, bare = setup
    new_main = _main_commit(fixture_repo["seed"], bare, "docs/runbook.md", "# Runbook\nv2\n", "x")
    verify = Verifier()
    res = _land(ws, base, head, FakePulls(bare), verify)
    assert res.outcome == "landed"
    assert verify.ran == [res.vault_head] and res.vault_head != head
    assert ws.is_ancestor(REPO, new_main, res.vault_head)
    assert git(bare, "rev-parse", f"refs/heads/{BRANCH}") == res.verified_sha
    assert ws.published_sha(REPO, BRANCH) == res.verified_sha
    assert ws.is_ancestor(REPO, new_main, res.verified_sha)


def test_rebase_reverify_red_on_the_rebased_sha_is_rework_and_nothing_is_pushed(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path]
) -> None:
    ws, base, head, bare = setup
    _main_commit(fixture_repo["seed"], bare, "docs/runbook.md", "# Runbook\nv2\n", "x")
    res = _land(ws, base, head, FakePulls(bare), Verifier(green=False))
    assert res.outcome == "rework" and res.verified_sha is None
    assert "verifier" in res.reason
    assert ws.published_sha(REPO, BRANCH) is None  # nothing sent


def test_rebase_reverify_a_logic_conflict_is_rework_with_its_files_and_no_resolution(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path]
) -> None:
    """Main changed the same lines of a file the task leases that is not generated: no
    model resolves it; REWORK names the files, and the verifier never runs."""
    ws, base, head, bare = setup
    _main_commit(fixture_repo["seed"], bare, GEN, "# Feature map\nsomething else\n", "x")
    verify = Verifier()
    res = _land(ws, base, head, FakePulls(bare), verify)
    assert res.outcome == "rework"
    assert res.conflicts == [GEN] and verify.ran == []
    assert ws.published_sha(REPO, BRANCH) is None


def test_rebase_reverify_a_generated_only_conflict_is_regenerated_and_retried_once(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path]
) -> None:
    """The only conflict is in a generated file: vigild takes main's side, reruns the
    generator once, verifies the result and lands it."""
    ws, base, head, bare = setup
    _main_commit(fixture_repo["seed"], bare, GEN, "# Feature map\nmain's row\n", "x")
    regen, verify = Regen(), Verifier()
    res = _land(ws, base, head, FakePulls(bare), verify, generated=[GEN], regen=regen)
    assert res.outcome == "landed" and regen.runs == 1
    assert verify.ran == [res.vault_head]
    assert ws.read_blob(REPO, res.verified_sha, GEN) == regen.text


def test_rebase_reverify_a_generated_conflict_that_recurs_is_rework_after_one_retry(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:  # fmt: skip
    """Main moves again while the regenerated head is being built: one retry only."""
    ws, base, head, bare = setup
    seed = fixture_repo["seed"]
    _main_commit(seed, bare, GEN, "# Feature map\nmain's row\n", "x")

    class Racing(Regen):
        def __call__(self, checkout: Path, paths: list[str]) -> None:
            super().__call__(checkout, paths)
            _main_commit(seed, bare, GEN, f"# Feature map\nrace {self.runs}\n", "race")

    regen = Racing()
    res = _land(ws, base, head, FakePulls(bare), Verifier(), generated=[GEN], regen=regen)
    assert res.outcome == "rework" and regen.runs <= 2
    assert ws.published_sha(REPO, BRANCH) is None


def test_rebase_reverify_republish_rebuilds_the_pr_title_and_body_from_the_current_head(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path]
) -> None:
    """#221: landing an open PR rewrites its body from the head it lands (redacted), so it
    never describes an earlier attempt; the body names the verified SHA."""
    ws, base, head, bare = setup
    pulls = EditablePulls(bare)
    url = _pub(ws, base, head, pulls)
    _main_commit(fixture_repo["seed"], bare, "docs/runbook.md", "# Runbook\nv2\n", "x")
    res = _land(ws, base, head, pulls, Verifier(), existing=url, body="attempt 2 body")
    assert res.outcome == "landed"
    (upd,) = pulls.updates
    assert upd["url"] == url and "attempt 2 body" in upd["body"]
    assert res.verified_sha[:12] in upd["body"]


def test_sha_binding_a_merge_is_accepted_only_when_the_pr_head_is_the_verified_sha() -> None:
    m = _landing()
    sha = "a" * 40
    assert m.merge_allowed(pr_head=sha, verified_sha=sha) is True
    assert m.merge_allowed(pr_head="b" * 40, verified_sha=sha) is False
    assert m.merge_allowed(pr_head=sha, verified_sha=None) is False  # never verified


def test_sha_binding_a_push_to_the_branch_after_landing_unbinds_the_verdict(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path]
) -> None:
    """Someone pushes to the `vigil/*` branch after vigild landed it: the PR head is no
    longer the verified SHA, so the merge is refused (and BranchMoved still guards the
    next push)."""
    ws, base, head, bare = setup
    res = _land(ws, base, head, FakePulls(bare), Verifier())
    pushed = _other_commit(bare, res.verified_sha, "a hand push")
    git(bare, "update-ref", f"refs/heads/{BRANCH}", pushed)
    m = _landing()
    tip = git(bare, "rev-parse", f"refs/heads/{BRANCH}")
    assert m.merge_allowed(pr_head=tip, verified_sha=res.verified_sha) is False


def test_stale_a_landed_pr_whose_leased_paths_changed_on_main_must_be_reverified(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path]
) -> None:
    """The staleness sweep: before a card says "ready", a PR verified on a main that has
    since changed a path its task leases is stale (re-rebase and re-verify); a change to
    other paths is not."""
    ws, base, head, bare = setup
    seed = fixture_repo["seed"]
    res = _land(ws, base, head, FakePulls(bare), Verifier())
    m = _landing()
    scope = ["docs/feature-map.md"]
    _main_commit(seed, bare, "docs/runbook.md", "# Runbook\nv3\n", "unrelated")
    assert m.is_stale(ws, repo=REPO, verified_on=res.main_sha, scope=scope, token=None) is False
    _main_commit(seed, bare, GEN, "# Feature map\nanother row\n", "leased path")
    assert m.is_stale(ws, repo=REPO, verified_on=res.main_sha, scope=scope, token=None) is True


def test_stale_the_sweep_relands_a_stale_pr_before_it_is_ready(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path]
) -> None:
    ws, base, head, bare = setup
    first = _land(ws, base, head, FakePulls(bare), Verifier())
    _main_commit(fixture_repo["seed"], bare, "docs/runbook.md", "# Runbook\nv9\n", "main moved")
    verify = Verifier()
    again = _land(ws, base, head, FakePulls(bare), verify)
    assert again.outcome == "landed" and again.verified_sha != first.verified_sha
    assert verify.ran == [again.vault_head]


def test_the_landing_queue_is_one_lander_per_repo_first_approved_first() -> None:
    """One landing mutex per repo, FIFO by approval time; repos do not wait on each other."""
    q = _landing().LandingQueue()
    q.add("o/a", "t2", approved_at="2026-11-01T10:05:00+00:00")
    q.add("o/a", "t1", approved_at="2026-11-01T10:00:00+00:00")
    q.add("o/b", "u1", approved_at="2026-11-01T10:10:00+00:00")
    assert q.take("o/a") == "t1"
    assert q.take("o/a") is None  # t1 is landing: the repo's one lander is busy
    assert q.take("o/b") == "u1"  # another repo is not held up
    q.done("o/a", "t1")
    assert q.take("o/a") == "t2"


def test_every_git_call_in_landing_goes_through_gitsafe(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """p3-09 (owner, 2026-11-01): landing runs git only through `vigild.gitsafe`: every git
    process it starts carries gitsafe's hardening (no hooks, no system or global config, no
    external diff), and the module never imports `subprocess` itself."""
    import ast
    import inspect
    import subprocess as sp

    from vigild import gitsafe

    m = _landing()
    tree = ast.parse(inspect.getsource(m))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)
                for a in n.names} | {n.module for n in ast.walk(tree)
                if isinstance(n, ast.ImportFrom) and n.module}  # fmt: skip
    assert not imported & {"subprocess", "os"}, imported
    ws, base, head, bare = setup
    _main_commit(fixture_repo["seed"], bare, GEN, "# Feature map\nmain's row\n", "x")
    real = sp.run
    seen: list[list[str]] = []

    def spy(argv: Any, *a: Any, **kw: Any) -> Any:
        cwd = Path(str(kw.get("cwd", "")))
        # vigild's own git, in its data dir (the fake GitHub's helper git is not landing's)
        if isinstance(argv, list) and argv and argv[0] == "git" and ws.data_dir in cwd.parents:
            seen.append(argv)
        return real(argv, *a, **kw)

    monkeypatch.setattr(sp, "run", spy)
    res = _land(ws, base, head, FakePulls(bare), Verifier(), generated=[GEN], regen=Regen())
    assert res.outcome == "landed"
    assert seen, "landing ran no git at all"
    hardening = list(gitsafe.HARDENING)
    for argv in seen:
        assert argv[1 : 1 + len(hardening)] == hardening, argv[:6]


# --- the review of the landing library (2026-11-01) ----------------------------------


def test_rebase_reverify_a_non_ascii_generated_conflict_is_regenerated(
    tmp_path: Path, fixture_repo: dict[str, Path]
) -> None:
    """merge-tree names are read NUL-separated, so a non-ASCII path still matches the
    generated list instead of coming back C-quoted."""
    ws = Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"]))
    gen = "docs/fé.md"
    seed, bare = fixture_repo["seed"], fixture_repo["bare"]
    _main_commit(seed, bare, gen, "base\n", "a generated file")
    clone = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    (clone / gen).write_text("worker\n")
    r = finish_session(clone, tmp_path / "out", branch=BRANCH, base_sha=base)
    head = ws.import_result(REPO, TID, tmp_path / "out", BRANCH, base, head=r["head"])
    _main_commit(seed, bare, gen, "main\n", "main changed it")
    regen = Regen()
    res = _landing().land(
        ws, repo=REPO, task_id=TID, branch=BRANCH, head=head, base_sha=base, base="main",
        scope=[gen], generated=[gen], verify=Verifier(), regenerate=regen,
        pulls=FakePulls(bare), title="t", body="b", existing=None, token=None,
    )  # fmt: skip
    assert res.outcome == "landed" and regen.runs == 1


def test_rebase_reverify_a_change_already_on_main_is_not_sent(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path]
) -> None:
    ws, base, head, bare = setup
    _main_commit(fixture_repo["seed"], bare, GEN, "# Feature map\nrate limit\n", "same change")
    verify = Verifier()
    res = _land(ws, base, head, FakePulls(bare), verify)
    assert res.outcome == "rework" and "already on main" in res.reason
    assert verify.ran == [] and ws.published_sha(REPO, BRANCH) is None


def test_rebase_reverify_never_regenerates_over_a_workers_symlink(
    tmp_path: Path, fixture_repo: dict[str, Path]
) -> None:
    """A symlink the worker committed must never lead the generator off the checkout."""
    ws = Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"]))
    clone = ws.clone(REPO, TID, branch=BRANCH, base="main")
    base = ws.base_sha(TID)
    (clone / "docs" / "feature-map.md").write_text("# Feature map\nrate limit\n")
    (clone / "docs" / "home").symlink_to("/Users")
    r = finish_session(clone, tmp_path / "out", branch=BRANCH, base_sha=base)
    head = ws.import_result(REPO, TID, tmp_path / "out", BRANCH, base, head=r["head"])
    _main_commit(fixture_repo["seed"], fixture_repo["bare"], GEN, "# Feature map\nmain\n", "x")
    regen = Regen()
    with pytest.raises(PublishError, match="symlink"):
        _landing().land(
            ws, repo=REPO, task_id=TID, branch=BRANCH, head=head, base_sha=base, base="main",
            scope=["docs/**"], generated=[GEN], verify=Verifier(), regenerate=regen,
            pulls=FakePulls(fixture_repo["bare"]), title="t", body="b", existing=None,
            token=None,
        )  # fmt: skip
    assert regen.runs == 0


def test_sha_binding_landing_again_after_a_hand_push_is_branch_moved(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path]
) -> None:
    """A hand push to the `vigil/*` branch after landing: the next landing refuses
    (BranchMoved) and overwrites nothing."""
    ws, base, head, bare = setup
    first = _land(ws, base, head, FakePulls(bare), Verifier())
    pushed = _other_commit(bare, first.verified_sha, "a hand push")
    git(bare, "update-ref", f"refs/heads/{BRANCH}", pushed)
    _main_commit(fixture_repo["seed"], bare, "docs/runbook.md", "# Runbook\nv4\n", "x")
    with pytest.raises(PublishError) as raised:
        _land(ws, base, head, FakePulls(bare), Verifier())
    assert type(raised.value).__name__ == "BranchMoved"
    assert git(bare, "rev-parse", f"refs/heads/{BRANCH}") == pushed


def test_stale_a_change_to_a_generated_file_counts(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path]
) -> None:
    ws, base, head, bare = setup
    res = _land(ws, base, head, FakePulls(bare), Verifier())
    _main_commit(fixture_repo["seed"], bare, "docs/table.md", "rows\n", "a generated table")
    m = _landing()
    kw = {"repo": REPO, "verified_on": res.main_sha, "scope": [GEN], "token": None}
    assert m.is_stale(ws, **kw) is False
    assert m.is_stale(ws, generated=["docs/table.md"], **kw) is True


def test_the_landing_queue_orders_approval_times_as_instants() -> None:
    q = _landing().LandingQueue()
    q.add("o/a", "later", approved_at="2026-11-01T10:30:00+00:00")
    q.add("o/a", "earlier", approved_at="2026-11-01T06:00:00-04:00")  # 10:00 UTC
    assert q.take("o/a") == "earlier"


# --- REWORK publish (owner, 2026-11-01): same branch, lease on vigild's own send --------


def _rebuilt_on_new_main(
    ws: Workspace, tmp_path: Path, fixture_repo: dict[str, Path]
) -> tuple[str, str]:
    """A REWORK worker's head: main moved, the task rebuilt from the new main."""
    seed, bare = fixture_repo["seed"], fixture_repo["bare"]
    _main_commit(seed, bare, "docs/runbook.md", "# Runbook\nnew main\n", "main moved")
    clone = ws.clone(REPO, f"{TID}-r", branch=BRANCH, base="main")
    base2 = ws.base_sha(f"{TID}-r")
    (clone / "docs" / "feature-map.md").write_text("# Feature map\nrate limit, again\n")
    r = finish_session(clone, tmp_path / "out2", branch=BRANCH, base_sha=base2)
    head2 = ws.import_result(REPO, f"{TID}-r", tmp_path / "out2", BRANCH, base2, head=r["head"])
    return base2, head2


def test_rework_replace_keeps_the_old_tip_and_sends_the_rebuilt_head(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path], tmp_path: Path
) -> None:
    """Guard 1: before the force-with-lease, the old tip is kept in the vault as
    refs/vigil/rework/<task>/<n>; the branch then holds the rebuilt head, on the new main."""
    ws, base, head, bare = setup
    pulls = EditablePulls(bare)
    url = _pub(ws, base, head, pulls)
    old = git(bare, "rev-parse", f"refs/heads/{BRANCH}")
    base2, head2 = _rebuilt_on_new_main(ws, tmp_path, fixture_repo)
    publish(ws, repo=REPO, head=head2, base_sha=base2, branch=BRANCH, base="main",
            title="t2", body="rebuilt", pulls=pulls, scope=["docs/feature-map.md"],
            existing=url, replace=f"{TID}/1")  # fmt: skip
    new = git(bare, "rev-parse", f"refs/heads/{BRANCH}")
    assert new != old and ws.is_ancestor(REPO, base2, new)
    assert git(ws.vault(REPO), "rev-parse", f"refs/vigil/rework/{TID}/1") == old
    assert pulls.updates and "rebuilt" in pulls.updates[-1]["body"]  # #221


def test_rework_replace_over_a_tip_vigild_did_not_send_is_branch_moved(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path], tmp_path: Path
) -> None:
    """Guard 3: a REWORK replaces only vigild's own send."""
    ws, base, head, bare = setup
    url = _pub(ws, base, head, FakePulls(bare))
    outside = _other_commit(bare, git(bare, "rev-parse", f"refs/heads/{BRANCH}"), "a hand push")
    git(bare, "update-ref", f"refs/heads/{BRANCH}", outside)
    base2, head2 = _rebuilt_on_new_main(ws, tmp_path, fixture_repo)
    with pytest.raises(PublishError) as raised:
        publish(ws, repo=REPO, head=head2, base_sha=base2, branch=BRANCH, base="main",
                title="t", body="b", pulls=FakePulls(bare), scope=["docs/feature-map.md"],
                existing=url, replace=f"{TID}/1")  # fmt: skip
    assert type(raised.value).__name__ == "BranchMoved"
    assert git(bare, "rev-parse", f"refs/heads/{BRANCH}") == outside


def test_a_plain_publish_of_a_rebuilt_head_still_only_fast_forwards(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path], tmp_path: Path
) -> None:
    """Guard 3: without `replace`, a head on a new base can't replace vigild's own send:
    every path but landing and REWORK stays fast-forward-only."""
    ws, base, head, bare = setup
    url = _pub(ws, base, head, FakePulls(bare))
    sent = git(bare, "rev-parse", f"refs/heads/{BRANCH}")
    base2, head2 = _rebuilt_on_new_main(ws, tmp_path, fixture_repo)
    publish(ws, repo=REPO, head=head2, base_sha=base2, branch=BRANCH, base="main",
            title="t", body="b", pulls=FakePulls(bare), scope=["docs/feature-map.md"],
            existing=url)  # fmt: skip
    tip = git(bare, "rev-parse", f"refs/heads/{BRANCH}")
    assert ws.is_ancestor(REPO, sent, tip)  # chained on the last send: a fast-forward


def test_rework_replace_retried_after_a_crash_keeps_the_first_old_tip(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path], tmp_path: Path
) -> None:
    """Round 2: a replace retried after the push (vigild died before clearing its mark)
    never overwrites the kept old tip with the new one."""
    ws, base, head, bare = setup
    pulls = EditablePulls(bare)
    url = _pub(ws, base, head, pulls)
    old = git(bare, "rev-parse", f"refs/heads/{BRANCH}")
    base2, head2 = _rebuilt_on_new_main(ws, tmp_path, fixture_repo)
    for _ in range(2):
        publish(ws, repo=REPO, head=head2, base_sha=base2, branch=BRANCH, base="main",
                title="t2", body="rebuilt", pulls=pulls, scope=["docs/feature-map.md"],
                existing=url, replace=f"{TID}/1")  # fmt: skip
    assert git(ws.vault(REPO), "rev-parse", f"refs/vigil/rework/{TID}/1") == old


def test_rework_replace_after_a_crash_before_the_record_is_recorded_not_pushed_again(
    setup: tuple[Workspace, str, str, Path], fixture_repo: dict[str, Path], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    """Owner, 2026-11-01: vigild pushed the rebuilt head and died before recording it. The
    retry finds the remote tip already equal to what it would send: it records it and goes
    on. No BranchMoved, no second push, and the kept ref is still the old tip."""
    ws, base, head, bare = setup
    pulls = EditablePulls(bare)
    url = _pub(ws, base, head, pulls)
    old = git(bare, "rev-parse", f"refs/heads/{BRANCH}")
    base2, head2 = _rebuilt_on_new_main(ws, tmp_path, fixture_repo)
    kw: dict[str, Any] = dict(repo=REPO, head=head2, base_sha=base2, branch=BRANCH,
                              base="main", title="t2", body="rebuilt", pulls=pulls,
                              scope=["docs/feature-map.md"], existing=url,
                              replace=f"{TID}/1")  # fmt: skip
    record = ws.record_published

    def crash(*a: Any) -> None:
        raise SystemExit("vigild died after the push")

    monkeypatch.setattr(ws, "record_published", crash)
    with pytest.raises(SystemExit):
        publish(ws, **kw)
    sent = git(bare, "rev-parse", f"refs/heads/{BRANCH}")
    assert sent != old
    monkeypatch.setattr(ws, "record_published", record)
    pushes: list[Any] = []
    real_push = ws.push
    monkeypatch.setattr(ws, "push", lambda *a, **k: (pushes.append(a), real_push(*a, **k)))
    publish(ws, **kw)
    assert pushes == []
    assert ws.published_sha(REPO, BRANCH) == sent
    assert git(bare, "rev-parse", f"refs/heads/{BRANCH}") == sent
    assert git(ws.vault(REPO), "rev-parse", f"refs/vigil/rework/{TID}/1") == old


def test_hold_lands_one_job_per_repo_and_the_earliest_approved_waiter_goes_next() -> None:
    """p3-09 PR 3: a lander holds its repo; waiters go in approval order once it lets go;
    another repo is never held up."""
    import threading

    q = _landing().LandingQueue()
    order: list[str] = []
    first = q.hold("o/a", "j0", approved_at="2026-11-01T09:00:00+00:00")
    first.__enter__()

    def lander(job: str, at: str, repo: str = "o/a") -> threading.Thread:
        def run() -> None:
            with q.hold(repo, job, approved_at=at):
                order.append(job)

        th = threading.Thread(target=run)
        th.start()
        return th

    late = lander("j2", "2026-11-01T10:05:00+00:00")
    early = lander("j1", "2026-11-01T10:00:00+00:00")
    other = lander("k1", "2026-11-01T11:00:00+00:00", repo="o/b")
    other.join(timeout=5)
    assert order == ["k1"]  # o/b did not wait on o/a
    for _ in range(100):  # both o/a waiters are queued before the holder lets go
        if len(q._waiting.get("o/a", [])) == 2:
            break
        threading.Event().wait(0.01)
    first.__exit__(None, None, None)
    late.join(timeout=5)
    early.join(timeout=5)
    assert order == ["k1", "j1", "j2"]


def test_hold_lets_go_when_the_landing_raises() -> None:
    q = _landing().LandingQueue()
    with pytest.raises(RuntimeError), q.hold("o/a", "j1", approved_at="2026-11-01T10:00:00+00:00"):
        raise RuntimeError("the verifier failed")
    with q.hold("o/a", "j2", approved_at="2026-11-01T10:05:00+00:00"):
        pass  # not held forever by j1

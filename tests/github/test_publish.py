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

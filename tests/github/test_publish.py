"""vigild publishes from the host (P2): checks, push, draft PR. Workers hold no token."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import git
from vigild.github.publish import PublishError, publish


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
        # GitHub checks the branch exists on the remote; so does the fake.
        git(self.bare, "rev-parse", "--verify", f"refs/heads/{head}")
        n = len(self.prs) + 1
        self.prs.append(
            {"repo": repo, "head": head, "base": base, "title": title, "body": body, "draft": draft}
        )
        return f"https://github.com/{repo}/pull/{n}"


@pytest.fixture
def work(fixture_repo: dict[str, Path], tmp_path: Path) -> Path:
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(fixture_repo["bare"]), str(clone))
    git(clone, "config", "user.email", "w@vigil.invalid")
    git(clone, "config", "user.name", "w")
    git(clone, "checkout", "-q", "-b", "vigil/fx-0001-w1-doc")
    (clone / "docs" / "feature-map.md").write_text("# Feature map\nrate limit\n")
    git(clone, "commit", "-qam", "doc the limit")
    return clone


def test_publish_pushes_the_branch_and_opens_a_draft(
    work: Path, fixture_repo: dict[str, Path]
) -> None:
    pulls = FakePulls(fixture_repo["bare"])
    url = publish(
        work,
        repo="o/fixture",
        branch="vigil/fx-0001-w1-doc",
        base="main",
        title="t",
        body="b",
        pulls=pulls,
        scope=["docs/feature-map.md"],
    )
    assert url == "https://github.com/o/fixture/pull/1"
    assert pulls.prs[0]["draft"] is True and pulls.prs[0]["base"] == "main"
    assert (
        git(fixture_repo["bare"], "log", "-1", "--format=%s", "vigil/fx-0001-w1-doc")
        == "doc the limit"
    )
    # main is untouched
    assert git(fixture_repo["bare"], "log", "-1", "--format=%s", "main") == "seed"


@pytest.mark.parametrize("branch", ["main", "master", "feature/x", "vigil/../main"])
def test_publish_refuses_anything_but_a_vigil_branch(
    work: Path, fixture_repo: dict[str, Path], branch: str
) -> None:
    with pytest.raises(PublishError):
        publish(
            work,
            repo="o/fixture",
            branch=branch,
            base="main",
            title="t",
            body="b",
            pulls=FakePulls(fixture_repo["bare"]),
            scope=["docs/feature-map.md"],
        )


def test_publish_refuses_when_head_is_not_the_branch(
    work: Path, fixture_repo: dict[str, Path]
) -> None:
    git(work, "checkout", "-q", "main")
    with pytest.raises(PublishError, match="checked out"):
        publish(
            work,
            repo="o/fixture",
            branch="vigil/fx-0001-w1-doc",
            base="main",
            title="t",
            body="b",
            pulls=FakePulls(fixture_repo["bare"]),
            scope=["docs/feature-map.md"],
        )


def test_publish_never_falls_back_to_a_non_draft(work: Path, fixture_repo: dict[str, Path]) -> None:
    pulls = FakePulls(fixture_repo["bare"], refuse_draft=True)
    with pytest.raises(PublishError, match="Draft"):
        publish(
            work,
            repo="o/fixture",
            branch="vigil/fx-0001-w1-doc",
            base="main",
            title="t",
            body="b",
            pulls=pulls,
            scope=["docs/feature-map.md"],
        )
    assert pulls.prs == []


def test_publish_with_nothing_committed_fails(
    fixture_repo: dict[str, Path], tmp_path: Path
) -> None:
    clone = tmp_path / "c2"
    git(tmp_path, "clone", "-q", str(fixture_repo["bare"]), str(clone))
    git(clone, "checkout", "-q", "-b", "vigil/empty")
    with pytest.raises(PublishError, match="no commits"):
        publish(
            clone,
            repo="o/fixture",
            branch="vigil/empty",
            base="main",
            title="t",
            body="b",
            pulls=FakePulls(fixture_repo["bare"]),
            scope=["docs/feature-map.md"],
        )


def test_publish_refuses_files_outside_the_scope(work: Path, fixture_repo: dict[str, Path]) -> None:
    (work / "README.md").write_text("sneaky\n")
    git(work, "commit", "-qam", "out of scope")
    pulls = FakePulls(fixture_repo["bare"])
    with pytest.raises(PublishError, match=r"README\.md"):
        publish(
            work,
            repo="o/fixture",
            branch="vigil/fx-0001-w1-doc",
            base="main",
            title="t",
            body="b",
            pulls=pulls,
            scope=["docs/feature-map.md"],
        )
    # nothing was pushed
    with pytest.raises(subprocess.CalledProcessError):
        git(fixture_repo["bare"], "rev-parse", "--verify", "refs/heads/vigil/fx-0001-w1-doc")
    assert pulls.prs == []


def test_vigil_artifacts_are_always_in_scope(work: Path, fixture_repo: dict[str, Path]) -> None:
    (work / ".vigil" / "fx-0001" / "fx-0001-w1").mkdir(parents=True)
    (work / ".vigil" / "fx-0001" / "fx-0001-w1" / "worker_report.json").write_text("{}")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "report")
    url = publish(
        work,
        repo="o/fixture",
        branch="vigil/fx-0001-w1-doc",
        base="main",
        title="t",
        body="b",
        pulls=FakePulls(fixture_repo["bare"]),
        scope=["docs/feature-map.md"],
    )
    assert url.endswith("/pull/1")

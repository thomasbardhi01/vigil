"""vigil doctor: production runs from a clean checkout at the deployed SHA,
and the launchd plist's WorkingDirectory is that checkout (#189)."""

from __future__ import annotations

import plistlib
from pathlib import Path

from vigild import doctor
from vigild.gitsafe import git

NAME = "prod checkout"


def _repo(path: Path) -> str:
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q",
        "--allow-empty", "-m", "init")  # fmt: skip
    (path / "f.txt").write_text("x\n")
    git(path, "add", ".")
    git(path, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "f")
    return git(path, "rev-parse", "HEAD")


class Setup:
    def __init__(self, tmp: Path) -> None:
        self.prod = tmp / "vigil-prod"
        self.sha = _repo(self.prod)
        self.data = tmp / "data"
        self.data.mkdir()
        (self.data / "deployed_sha").write_text(self.sha + "\n")
        self.plist = tmp / "vigild.plist"
        self.point(str(self.prod))

    def point(self, wd: str) -> None:
        self.plist.write_bytes(
            plistlib.dumps({"Label": "dev.vigil.vigild", "WorkingDirectory": wd})
        )

    def check(self) -> doctor.Check:
        return doctor.prod_checkout_check(self.prod, self.plist, self.data)


def test_passes_for_a_clean_checkout_at_the_deployed_sha(tmp_path: Path) -> None:
    c = Setup(tmp_path).check()
    assert c.name == NAME and c.ok is True


def test_fails_on_a_dirty_tree(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    (s.prod / "f.txt").write_text("changed\n")
    c = s.check()
    assert c.ok is False and "uncommitted" in c.note


def test_fails_on_an_untracked_file(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    (s.prod / "new.txt").write_text("x\n")
    c = s.check()
    assert c.ok is False and "uncommitted" in c.note


def test_fails_when_head_is_not_the_deployed_sha(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    (s.data / "deployed_sha").write_text("0" * 40 + "\n")
    c = s.check()
    assert c.ok is False and "deployed" in c.note


def test_fails_when_nothing_records_a_deploy(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    (s.data / "deployed_sha").unlink()
    c = s.check()
    assert c.ok is False and "deployed_sha" in c.note


def test_fails_when_the_plist_points_elsewhere(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    s.point("/Users/x/Documents/vigil")
    c = s.check()
    assert c.ok is False
    assert "production runs from /Users/x/Documents/vigil" in c.note
    assert str(s.prod) in c.note and "Switch production to ~/vigil-prod" in c.note


def test_fails_when_the_prod_dir_is_missing(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    s.prod = tmp_path / "absent"
    s.point(str(s.prod))
    c = s.check()
    assert c.ok is False and "does not exist" in c.note


def test_fails_when_the_prod_dir_is_not_a_checkout(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    s.prod = plain
    s.point(str(plain))
    c = s.check()
    assert c.ok is False and "not a git checkout" in c.note


def test_fails_without_crashing_when_the_plist_is_missing_or_broken(tmp_path: Path) -> None:
    s = Setup(tmp_path)
    s.plist.write_bytes(b"not a plist")
    assert s.check().ok is False
    s.plist.unlink()
    c = s.check()
    assert c.ok is False and "plist" in c.note

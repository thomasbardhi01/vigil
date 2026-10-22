"""Review round 1, item 10: vigild checks each repo's real visibility through
the App and refuses to start on a mismatch, or when it can't check. Mocked:
this test never calls GitHub."""

from __future__ import annotations

from typing import Any

import pytest

from vigild.config import Config
from vigild.repos import RepoPolicyError, verify_visibility


class FakeGitHub:
    def __init__(self, private: dict[str, Any]) -> None:
        self.private = private
        self.asked: list[str] = []

    def is_private(self, repo: str) -> bool:
        self.asked.append(repo)
        v = self.private[repo]
        if isinstance(v, Exception):
            raise v
        return bool(v)


def test_matching_visibility_passes(cfg: Config) -> None:
    gh = FakeGitHub({"thomasbardhi01/parkagent": False, "thomasbardhi01/vigil": True})
    verify_visibility(cfg, gh.is_private)
    assert sorted(gh.asked) == sorted(cfg.repos.repos)


def test_a_public_yaml_entry_for_a_private_repo_stops_vigild(cfg: Config) -> None:
    gh = FakeGitHub({"thomasbardhi01/parkagent": True, "thomasbardhi01/vigil": True})
    with pytest.raises(RepoPolicyError, match="parkagent.*private"):
        verify_visibility(cfg, gh.is_private)


def test_a_failed_check_stops_vigild(cfg: Config) -> None:
    gh = FakeGitHub({"thomasbardhi01/parkagent": OSError("timeout"), "thomasbardhi01/vigil": True})
    with pytest.raises(RepoPolicyError, match="can't check"):
        verify_visibility(cfg, gh.is_private)

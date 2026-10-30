"""Validation runs the suite as CI does (#191): vigil's `dev_suites.tests` and the
`test` job of ci.yml run the same pytest selection. The only differences allowed are
what validation needs with no network: `--offline` on `uv run` and `-p no:cacheprovider`."""

from __future__ import annotations

from typing import Any

import yaml

from vigild.devimage import ROOT
from vigild.shellwords import parse

CI = ROOT / ".github" / "workflows" / "ci.yml"
REPOS = ROOT / "configs" / "repos.yaml"
OFFLINE = ["--offline"]
NO_CACHE = ["-p", "no:cacheprovider"]


def _split(cmd: str) -> tuple[list[str], list[str]]:
    """(the words before `pytest`, the pytest arguments) of the line's pytest command."""
    for c in parse(cmd).commands:
        if "pytest" in c.words:
            i = c.words.index("pytest")
            return list(c.words[:i]), list(c.words[i + 1 :])
    raise AssertionError(f"no pytest in {cmd!r}")


def _without(words: list[str], drop: list[str]) -> list[str]:
    n = len(drop)
    for i in range(len(words) - n + 1):
        if words[i : i + n] == drop:
            return words[:i] + words[i + n :]
    return words


def differences(ci_cmd: str, suite_cmd: str) -> list[str]:
    """What differs between the two commands beyond the allowed set."""
    ci_pre, ci_args = _split(ci_cmd)
    su_pre, su_args = _split(suite_cmd)
    su_pre, su_args = _without(su_pre, OFFLINE), _without(su_args, NO_CACHE)
    return [f"before pytest: {ci_pre} vs {su_pre}"] * (ci_pre != su_pre) + [
        f"arguments: {ci_args} vs {su_args}"
    ] * (ci_args != su_args)


def ci_test_command() -> str:
    steps = yaml.safe_load(CI.read_text())["jobs"]["test"]["steps"]
    (cmd,) = [s["run"] for s in steps if "pytest" in s.get("run", "")]
    return str(cmd)


def suite_command() -> str:
    repos: dict[str, Any] = yaml.safe_load(REPOS.read_text())["repos"]
    return str(repos["thomasbardhi01/vigil"]["dev_suites"]["tests"])


CI_CMD = "uv run pytest -q -n auto"


def test_the_allowed_differences_pass() -> None:
    assert differences(CI_CMD, "uv run --offline pytest -q -p no:cacheprovider -n auto") == []


def test_a_missing_flag_fails() -> None:
    assert differences(CI_CMD, "uv run --offline pytest -q -p no:cacheprovider")


def test_an_added_selection_fails() -> None:
    assert differences(CI_CMD, "uv run --offline pytest -q -n auto -m 'not slow'")
    assert differences(CI_CMD, "uv run --offline pytest -q -n auto tests/jobs")


def test_other_uv_flags_fail() -> None:
    assert differences(CI_CMD, "uv run --offline --frozen pytest -q -n auto")


def test_the_real_files_agree() -> None:
    assert differences(ci_test_command(), suite_command()) == []

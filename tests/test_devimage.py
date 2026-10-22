"""A pinned dev image per repo, validated nightly; dispatch refused on a stale one."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from vigild.config import Config
from vigild.db import Store
from vigild.devimage import DevImages, StaleDevImage

PA = "thomasbardhi01/parkagent"


class FakeDocker:
    def __init__(self) -> None:
        self.image_id = "sha256:aaa"
        self.exit = 0
        self.ran: list[tuple[str, str]] = []

    def image_id_of(self, image: str) -> str | None:
        return self.image_id

    def run_check(self, image: str, command: str) -> tuple[int, str]:
        self.ran.append((image, command))
        return self.exit, "git version 2.47\nPython 3.14.8"


class Clock:
    now = datetime(2026, 10, 22, 3, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def parts(cfg: Config, store: Store) -> tuple[DevImages, FakeDocker, Clock]:
    d, c = FakeDocker(), Clock()
    return DevImages(cfg, store, d, clock=c), d, c


def test_every_repo_pins_a_dev_image(cfg: Config) -> None:
    for repo, pol in cfg.repos.repos.items():
        assert pol.dev_image and pol.dev_image_check, repo


def test_never_validated_is_refused(parts: tuple[DevImages, FakeDocker, Clock]) -> None:
    images, _, _ = parts
    with pytest.raises(StaleDevImage, match="never validated"):
        images.ensure_fresh(PA)


def test_validated_is_fresh(parts: tuple[DevImages, FakeDocker, Clock]) -> None:
    images, docker, _ = parts
    assert images.validate(PA).ok
    assert docker.ran[0][1].startswith(f"({images.cfg.repo(PA).dev_image_check})")
    images.ensure_fresh(PA)


def test_older_than_a_day_and_a_bit_is_stale(parts: tuple[DevImages, FakeDocker, Clock]) -> None:
    images, _, clock = parts
    images.validate(PA)
    clock.now += timedelta(hours=27)
    with pytest.raises(StaleDevImage, match="27"):
        images.ensure_fresh(PA)


def test_a_rebuilt_image_needs_revalidating(parts: tuple[DevImages, FakeDocker, Clock]) -> None:
    images, docker, _ = parts
    images.validate(PA)
    docker.image_id = "sha256:bbb"
    with pytest.raises(StaleDevImage, match="changed"):
        images.ensure_fresh(PA)


def test_a_failed_check_is_stale(parts: tuple[DevImages, FakeDocker, Clock]) -> None:
    images, docker, _ = parts
    docker.exit = 1
    assert not images.validate(PA).ok
    with pytest.raises(StaleDevImage, match="failed"):
        images.ensure_fresh(PA)


def test_a_missing_image_is_refused(parts: tuple[DevImages, FakeDocker, Clock]) -> None:
    images, docker, _ = parts
    images.validate(PA)
    docker.image_id = None  # type: ignore[assignment]
    with pytest.raises(StaleDevImage, match="not present"):
        images.ensure_fresh(PA)


# --- blocker 4: a test the dev image can't run is refused, not accepted -------------------

from vigild.devimage import missing_tools, tools_in  # noqa: E402


def test_validation_checks_each_declared_tool(parts: tuple[DevImages, FakeDocker, Clock]) -> None:
    images, docker, _ = parts
    images.validate(PA)
    cmd = docker.ran[0][1]
    for tool in images.cfg.repo(PA).dev_image_tools:
        assert f"command -v {tool}" in cmd


@pytest.mark.parametrize(
    "cmd,tools",
    [
        ("pnpm test", ["pnpm"]),
        ("grep -q x a.md && test -f b", ["grep", "test"]),
        ("CI=1 pnpm -C server test | tail -3", ["pnpm", "tail"]),
        ("cd docs; grep x a.md || true", ["cd", "grep", "true"]),
    ],
)
def test_tools_in(cmd: str, tools: list[str]) -> None:
    assert tools_in(cmd) == tools


def test_parkagent_image_has_no_pnpm_so_pnpm_tests_are_refused(cfg: Config) -> None:
    assert missing_tools(cfg, PA, "pnpm -C server test") == ["pnpm"]
    assert missing_tools(cfg, PA, "grep -q 'rate limit' docs/feature-map.md") == []


def test_validate_all_covers_every_repo(parts: tuple[DevImages, FakeDocker, Clock]) -> None:  # item 21
    images, docker, _ = parts
    out = images.validate_all()
    assert sorted(v.repo for v in out) == sorted(images.cfg.repos.repos)
    for repo in images.cfg.repos.repos:
        images.ensure_fresh(repo)


def test_validation_is_due_daily(parts: tuple[DevImages, FakeDocker, Clock]) -> None:  # item 21
    images, _, clock = parts
    assert images.due(PA)
    images.validate(PA)
    assert not images.due(PA)
    clock.now += timedelta(hours=24, minutes=1)
    assert images.due(PA)

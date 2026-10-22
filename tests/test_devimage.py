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
    assert docker.ran[0][1] == images.cfg.repo(PA).dev_image_check
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

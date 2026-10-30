"""A deploy that leaves a repo's session image stale holds that repo's dispatch
behind one page, "image not fresh after deploy"; a validated rebuild releases it."""

from __future__ import annotations

from typing import Any

from tests.jobs.test_coord_loop import REPO, World
from tests.jobs.test_coord_loop import world as world
from tests.jobs.test_round2_runner import _pages
from tests.jobs.test_round3_runner import _building
from vigild.breakers import Kind
from vigild.jobs.model import JobState


def _only_fixture(w: World) -> None:
    for name in [r for r in w.runner.cfg.repos.repos if r != REPO]:
        del w.runner.cfg.repos.repos[name]


def _build(w: World) -> None:
    _only_fixture(w)
    base = w.runner.workspace.head_sha(REPO, "main")
    assert w.runner.session_images is not None
    w.runner.session_images.ensure_fresh(REPO, base)


def _stale(w: World) -> None:
    _build(w)
    w.store.x("DELETE FROM dev_images WHERE stage LIKE 'session%'")


def _held_pages(w: World) -> list[dict[str, Any]]:
    return [p for p in _pages(w) if "image not fresh after deploy" in p["title"]]


def test_a_fresh_image_at_start_pages_nothing_and_holds_nothing(world: World) -> None:
    w = world
    _build(w)
    assert w.runner.hold_stale_images() == []
    assert _held_pages(w) == []
    assert not w.runner.breakers.is_open(Kind.STALE_IMAGE, f"repo:{REPO}")


def test_a_stale_image_at_start_holds_the_repos_dispatch_behind_one_page(world: World) -> None:
    w = world
    job = _building(w)
    _stale(w)
    assert w.runner.hold_stale_images() == [REPO]
    assert w.runner.hold_stale_images() == [REPO]  # a second start pages nothing more
    (page,) = _held_pages(w)
    assert page["title"] == f"{REPO}: image not fresh after deploy"
    assert set(page["body"]["actions"]) == {"rebuild", "dismiss"}
    assert page["body"]["key"] and "newest_validated" in page["body"]["detail"]
    assert w.runner.breakers.is_open(Kind.STALE_IMAGE, f"repo:{REPO}")
    before = len(w.standin.specs)
    w.runner.dispatch(job)
    assert w.store.get_job(job).state is JobState.BLOCKED
    assert len(w.standin.specs) == before  # no session started


def test_a_validated_rebuild_releases_the_hold_and_the_job_dispatches(world: World) -> None:
    w = world
    job = _building(w)
    _stale(w)
    w.runner.hold_stale_images()
    before = len(w.standin.specs)
    w.runner.dispatch(job)
    assert w.store.get_job(job).state is JobState.BLOCKED
    assert w.runner.release_stale_images() == []  # nothing rebuilt yet
    _build(w)  # the rebuild records a validated session image for the key
    assert w.runner.release_stale_images() == [REPO]
    assert not w.runner.breakers.is_open(Kind.STALE_IMAGE, f"repo:{REPO}")
    assert _held_pages(w) == []
    assert w.store.get_job(job).state is not JobState.BLOCKED
    assert len(w.standin.specs) > before

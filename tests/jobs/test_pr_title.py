"""A PR title stays within GitHub's 256-character limit (vi-0008, 2026-10-29: a worker's
1,096-character goal became the title and GitHub refused the PR with 422)."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

from tests.jobs.test_coord_loop import SPEC, World, _approve, plan, world  # noqa: F401

GITHUB_TITLE_MAX = 256


def test_a_long_worker_goal_makes_a_short_title(world: World) -> None:
    w = world
    long_goal = "Replan after the worker ran out of cap. " + "Do the thing carefully. " * 60

    def long(j: str) -> tuple[str, str]:
        p = plan(j).replace('"goal": "feature map row"', f'"goal": "{long_goal}"')
        assert long_goal in p
        return SPEC, p

    w.standin.coord_drafts = [long]
    job = _approve(w)
    titles = [p["title"] for p in w.publisher.prs]
    assert titles, "nothing was published"
    assert all(len(t) <= GITHUB_TITLE_MAX for t in titles), [len(t) for t in titles]
    assert all(t.startswith(f"[vigil {job}] ") for t in titles)

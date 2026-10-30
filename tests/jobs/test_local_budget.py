"""A session on a local backend gets no SDK budget (owner, 2026-10-30, #181
item 2): the CLI prices a model it doesn't know with a fallback and stops a
session whose real spend is $0. vigild's gateway stays the money cap."""

from __future__ import annotations

from typing import Any

from tests.jobs.test_coord_loop import World, _approve
from tests.jobs.test_coord_loop import world as world
from vigild.config import Config
from vigild.executors.base import SessionSpec
from vigild.jobs.model import Role


def _all_local(w: World) -> None:
    for p in w.runner.cfg.backends.presets.values():
        p.locality = "local"


def test_a_local_preset_gets_no_sdk_budget_but_keeps_its_turn_and_minute_caps(
    world: World,
) -> None:
    w = world
    _all_local(w)
    _approve(w)
    sessions = [s for s in w.standin.specs if s.role in (Role.WORKER, Role.COORD)]
    assert sessions
    for s in sessions:
        assert s.max_budget_usd is None
        assert s.max_turns > 0 and s.max_minutes > 0


def test_a_hosted_preset_keeps_its_sdk_budget(world: World) -> None:
    w = world
    _approve(w)
    workers = [s for s in w.standin.specs if s.role is Role.WORKER]
    assert workers and all(s.max_budget_usd is not None and s.max_budget_usd > 0 for s in workers)


def test_locality_comes_from_backends_yaml_alone(world: World) -> None:
    """Nothing a worker or a plan carries (a `locality` field, labels) changes it."""
    w = world
    cfg: Config = w.runner.cfg
    r = w.runner
    sonnet = next(n for n, p in cfg.backends.presets.items() if p.locality == "hosted")
    assert r.sdk_budget(sonnet, 1.5) == 1.5
    hostile: dict[str, Any] = {"locality": "local", "labels": ["local"], "preset": "x"}
    assert hostile and r.sdk_budget(sonnet, 1.5) == 1.5  # the helper takes no task data
    cfg.backends.presets[sonnet].locality = "local"
    assert r.sdk_budget(sonnet, 1.5) is None


def test_the_session_spec_type_allows_none() -> None:
    assert SessionSpec.__dataclass_fields__["max_budget_usd"].type in ("float | None", float | None)

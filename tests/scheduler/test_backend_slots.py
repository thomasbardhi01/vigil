"""A local backend's slot count is its concurrency limit (owner, 2026-10-31): read
from llama-server's /props, never hard-coded; sessions beyond it queue (no failure,
no page) and start when a slot frees; an unreadable /props means 1 slot."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

import pytest

from tests.jobs.test_coord_loop import World, world  # noqa: F401
from tests.scheduler.test_fleet import _run
from vigild.config import Secrets
from vigild.scheduler import capacity as cap
from vigild.scheduler.capacity import Capacity


class Props:
    def __init__(self, slots: int | None, n_ctx: int = 32768, fail: bool = False) -> None:
        self.slots, self.n_ctx, self.fail = slots, n_ctx, fail
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> dict[str, Any]:
        self.calls.append((url, dict(headers)))
        if self.fail:
            raise TimeoutError("slow")
        return {"total_slots": self.slots, "default_generation_settings": {"n_ctx": self.n_ctx}}


def _local(w: World, props: Props, monkeypatch: pytest.MonkeyPatch) -> None:
    for p in w.runner.cfg.backends.presets.values():
        p.locality = "local"
    w.runner.capacity = Capacity(
        w.runner.cfg,
        Secrets({p.key_ref: "k-secret" for p in w.runner.cfg.backends.presets.values()}),
        w.store,
        fetch=props,
    )
    w.runner.slot_gate = cap.SlotGate(w.runner.capacity)
    monkeypatch.setattr(cap, "SLOT_POLL_SECONDS", 0.05)


def _events(w: World, kind: str) -> list[dict[str, Any]]:
    return [{**e.data, "task_id": e.task_id} for e in w.store.events() if e.type == kind]


def test_capacity_is_read_from_props_with_the_key_and_cached(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world
    props = Props(2, 16384)
    _local(w, props, monkeypatch)
    name = next(iter(w.runner.cfg.backends.presets))
    got = w.runner.capacity.get(name)  # type: ignore[union-attr]
    assert (got.total_slots, got.n_ctx) == (2, 16384)
    w.runner.capacity.get(name)  # type: ignore[union-attr]
    assert len(props.calls) == 1  # cached
    url, headers = props.calls[0]
    assert url.endswith("/props") and "/v1/" not in url
    assert headers == {"authorization": "Bearer k-secret"}
    (e,) = _events(w, "backend_capacity")
    assert (e["total_slots"], e["n_ctx"], e["preset"]) == (2, 16384, name)
    assert "k-secret" not in str(e)


def test_a_failed_props_read_is_one_slot_and_is_read_again(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world
    props = Props(2, fail=True)
    _local(w, props, monkeypatch)
    name = next(iter(w.runner.cfg.backends.presets))
    assert w.runner.capacity.get(name).total_slots == 1  # type: ignore[union-attr]
    assert w.runner.capacity.get(name).total_slots == 1  # type: ignore[union-attr]
    assert len(props.calls) == 2  # a failure is never cached
    assert _events(w, "backend_capacity")[0]["ok"] is False
    props.fail = False
    assert w.runner.capacity.get(name).total_slots == 2  # type: ignore[union-attr]


@pytest.mark.parametrize("slots, expect_peak", [(2, 2), (1, 1)])
def test_tower_tasks_run_up_to_the_slot_count_and_the_rest_queue(
    world: World, monkeypatch: pytest.MonkeyPatch, slots: int, expect_peak: int
) -> None:
    w = world
    _local(w, Props(slots), monkeypatch)
    job = _run(w, 3, delay=0.3)
    workers = [c for c in w.standin.calls if c[0] == "worker"]
    assert len(workers) == 3
    assert w.standin.max_running == expect_peak
    assert w.store.get_job(job).state.value == "ready"  # no failure, no hold
    assert not w.store.q("SELECT 1 FROM inbox_items WHERE kind='failure' OR kind='page'")
    queued = [e for e in _events(w, "queued") if e["for"] == "backend_slot"]
    dequeued = [e for e in _events(w, "dequeued") if e["for"] == "backend_slot"]
    assert len(queued) == 3 - slots and len(dequeued) == len(queued)


def test_hosted_dispatch_is_unchanged(world: World) -> None:
    w = world
    w.runner.capacity = Capacity(w.runner.cfg, Secrets({}), w.store, fetch=Props(1))
    w.runner.slot_gate = cap.SlotGate(w.runner.capacity)
    _run(w, 4, delay=0.3)
    assert w.standin.max_running == 3  # the fleet's limit, not the capacity of 1
    assert not _events(w, "backend_capacity")
    assert not [e for e in _events(w, "queued") if e["for"] == "backend_slot"]


def test_the_gate_wait_ends_when_cancelled() -> None:
    class Fixed:
        def limits(self, preset: str) -> int:
            return 1

    gate = cap.SlotGate(Fixed())  # type: ignore[arg-type]
    assert gate.acquire("p", cancelled=lambda: False, on_wait=lambda: None)
    stop = threading.Event()
    stop.set()
    waits: list[int] = []
    assert not gate.acquire("p", cancelled=stop.is_set, on_wait=lambda: waits.append(1), poll=0.01)
    assert waits == [1] and gate.live("p") == 1
    gate.release("p")
    assert gate.live("p") == 0

"""A local backend's slot count is its concurrency limit (owner, 2026-10-31): read
from llama-server's /props, never hard-coded; sessions beyond it queue (no failure,
no page) and start when a slot frees; an unreadable /props means 1 slot."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from typing import Any

import pytest

from tests.conftest import auth
from tests.jobs.test_coord_loop import World, _request, world  # noqa: F401
from tests.scheduler.test_fleet import _doc_work, _run, plan_n, spec_n
from vigild.config import Secrets
from vigild.scheduler import capacity as cap
from vigild.scheduler.capacity import Capacity


class Props:
    def __init__(self, slots: int | None, n_ctx: int = 262144, fail: bool = False) -> None:
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


def test_a_failed_props_read_is_one_slot_until_the_next_read(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world
    props = Props(2, fail=True)
    _local(w, props, monkeypatch)
    name = next(iter(w.runner.cfg.backends.presets))
    assert w.runner.capacity.get(name).total_slots == 1  # type: ignore[union-attr]
    assert w.runner.capacity.get(name).total_slots == 1  # type: ignore[union-attr]
    assert len(props.calls) == 1  # remembered for 30 s
    assert _events(w, "backend_capacity")[0]["ok"] is False
    props.fail = False
    w.runner.capacity.refresh(name)  # type: ignore[union-attr]
    assert w.runner.capacity.get(name).total_slots == 2  # type: ignore[union-attr]


@pytest.mark.parametrize("slots, expect_peak", [(2, 2), (1, 1)])
def test_tower_tasks_run_up_to_the_slot_count_and_the_rest_queue(
    world: World, monkeypatch: pytest.MonkeyPatch, slots: int, expect_peak: int
) -> None:
    """Deterministic: the slot holders wait on an event that is set once the gate
    has queued the rest (or after 10 s, which fails the queue assertion)."""
    w = world
    _local(w, Props(slots), monkeypatch)
    released = threading.Event()
    done = threading.Event()

    def watch() -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not done.is_set():
            n = sum(
                1
                for e in w.store.events()
                if e.type == "queued" and e.data["for"] == "backend_slot"
            )
            if n >= 3 - slots:
                break
            time.sleep(0.02)
        released.set()

    threading.Thread(target=watch, daemon=True).start()
    edit = _doc_work(0.0)

    def held(spec: Any, task: dict[str, Any]) -> None:
        released.wait(10)
        edit(spec, task)

    w.standin.coord_drafts = [lambda j: (spec_n(3), plan_n(j, 3))]
    w.standin.worker_edit = held
    job = _request(w)
    (item,) = w.client.get("/api/inbox", headers=auth(w.tokens.read)).json()["specs"]
    r = w.client.post(f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={})
    done.set()
    assert r.status_code == 200, r.text
    workers = [c for c in w.standin.calls if c[0] == "worker"]
    assert len(workers) == 3
    assert w.standin.max_running == expect_peak
    assert w.store.get_job(job).state.value == "ready"  # no failure, no hold
    assert not w.store.q("SELECT 1 FROM inbox_items WHERE kind='failure' OR kind='page'")
    queued = [e for e in _events(w, "queued") if e["for"] == "backend_slot"]
    dequeued = [e for e in _events(w, "dequeued") if e["for"] == "backend_slot"]
    assert len(queued) == 3 - slots and len(dequeued) == len(queued)


def test_presets_on_one_server_share_its_slots(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world
    _local(w, Props(2), monkeypatch)
    a, b = list(w.runner.cfg.backends.presets)[:2]
    w.runner.cfg.backends.presets[a].base_url = "http://tower:8080/v1"
    w.runner.cfg.backends.presets[b].base_url = "http://Tower:8080/v1/"
    gate = w.runner.slot_gate
    assert gate is not None
    assert gate.acquire(a, cancelled=lambda: False, on_wait=lambda: None)
    assert gate.acquire(b, cancelled=lambda: False, on_wait=lambda: None)
    waits: list[int] = []
    assert not gate.acquire(
        a, cancelled=lambda: True, on_wait=lambda: waits.append(1), poll=0.01
    )  # a third, across the two presets, has to wait
    assert waits == [1] and gate.live(a) == gate.live(b) == 2
    assert len(_events(w, "backend_capacity")) == 1  # one read for the one server


@pytest.mark.parametrize(
    "total, expect", [(10**9, 64), (64, 64), ("5", 1), (2.9, 1), (True, 1), (0, 1), (None, 1)]
)
def test_total_slots_is_a_real_int_clamped_to_64(
    world: World, monkeypatch: pytest.MonkeyPatch, total: Any, expect: int
) -> None:
    w = world
    _local(w, Props(total), monkeypatch)
    assert w.runner.capacity.limits(next(iter(w.runner.cfg.backends.presets))) == expect  # type: ignore[union-attr]


def test_a_401_is_named_and_not_read_again_within_30_seconds(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world
    calls: list[int] = []
    now = [100.0]

    def deny(url: str, headers: Mapping[str, str]) -> dict[str, Any]:
        calls.append(1)
        raise cap.StatusError("HTTP 401")

    _local(w, Props(2), monkeypatch)
    w.runner.capacity = Capacity(
        w.runner.cfg, Secrets({}), w.store, fetch=deny, clock=lambda: now[0]
    )
    name = next(iter(w.runner.cfg.backends.presets))
    assert w.runner.capacity.limits(name) == 1
    assert w.runner.capacity.limits(name) == 1
    assert len(calls) == 1
    (e,) = _events(w, "backend_capacity")
    assert e["error"] == "HTTP 401" and e["ok"] is False
    now[0] += 31
    w.runner.capacity.limits(name)
    assert len(calls) == 2


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

        def server(self, preset: str) -> str:
            return preset

        def refresh_if_stale(self, preset: str) -> None:
            pass

        def budget(self, preset: str) -> int | None:
            return None  # n_ctx unknown: slots only

        def reserve(self, preset: str) -> int:
            return 0

        def live_context(self, session_id: str) -> int:
            return 0

    gate = cap.SlotGate(Fixed())  # type: ignore[arg-type]
    assert gate.acquire("p", cancelled=lambda: False, on_wait=lambda: None)
    stop = threading.Event()
    stop.set()
    waits: list[int] = []
    assert not gate.acquire("p", cancelled=stop.is_set, on_wait=lambda: waits.append(1), poll=0.01)
    assert waits == [1] and gate.live("p") == 1
    gate.release("p")
    assert gate.live("p") == 0


# ---- the context budget (owner, 2026-10-31, branch a): the KV pool is shared ----


def _call(w: World, sid: str, preset: str, tokens: int, *, ended: bool = True) -> None:
    w.store.x(
        "INSERT OR IGNORE INTO sessions (id, role, status, created_at, ended_at, provenance)"
        " VALUES (?, 'worker', 'done', 'now', ?, 'local')",
        (sid, "now" if ended else None),
    )
    w.store.x(
        "INSERT INTO model_calls (session_id, purpose, provider, backend_preset, model,"
        " tokens_in, tokens_out, tokens_cache_read, tokens_cache_write_5m,"
        " tokens_cache_write_1h, cost_usd, ts, provenance)"
        " VALUES (?, 'session', 'local', ?, 'm', ?, 0, 0, 0, 0, 0, 'now', 'local')",
        (sid, preset, tokens),
    )


def _gate(w: World, peak: int, monkeypatch: pytest.MonkeyPatch, n_ctx: int = 65536) -> str:
    _local(w, Props(4, n_ctx), monkeypatch)
    name = next(iter(w.runner.cfg.backends.presets))
    if peak:
        _call(w, "hist", name, peak)
    return name


def _take(w: World, name: str, sid: str) -> bool:
    gate = w.runner.slot_gate
    assert gate is not None
    return gate.acquire(
        name, cancelled=lambda: True, on_wait=lambda: None, poll=0.01, session_id=sid
    )  # False means it had to wait


def test_no_history_expects_32768(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    name = _gate(world, 0, monkeypatch)
    assert world.runner.capacity.expected_peak(name) == 32768  # type: ignore[union-attr]


def test_the_second_session_waits_until_the_first_ends(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = _gate(world, 36 * 1024, monkeypatch)  # 36k + 36k > 64k - 8k
    gate = world.runner.slot_gate
    assert gate is not None
    assert _take(world, name, "a")
    assert not _take(world, name, "b")  # queued: no failure, no page
    assert gate.live(name) == 1
    gate.release(name, "a")
    assert _take(world, name, "b")
    assert [e for e in _events(world, "context_budget") if e["outcome"] == "queued"]
    assert not world.store.q("SELECT 1 FROM inbox_items")


def test_two_sessions_run_together_under_the_budget(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 20k of history is floored to 32k, so two fit only in a pool of 72k or more
    name = _gate(world, 20 * 1024, monkeypatch, n_ctx=81920)  # budget 72k >= 2 x 32k
    assert _take(world, name, "a") and _take(world, name, "b")
    assert not _take(world, name, "c")  # a third (96k) does not


def test_live_growth_raises_a_reservation(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    name = _gate(world, 0, monkeypatch, n_ctx=98304)  # budget 90k, expected 32k
    gate = world.runner.slot_gate
    assert gate is not None
    assert _take(world, name, "a") and gate.reserved(name) == 32768
    _call(world, "a", name, 70000, ended=False)  # the running session grew
    assert gate.reserved(name) == 70000
    assert not _take(world, name, "b")  # 70k + 32k > 90k: not admitted on the stale 32k


def test_a_task_bigger_than_the_server_routes_to_the_fallback(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vigild.contract.models import Spec, Task
    from vigild.router.rules import route

    cfg = world.runner.cfg
    name = next(n for n in cfg.backends.presets if n != cfg.routing.fallback)
    _gate(world, 0, monkeypatch)
    _call(world, "hist", name, 60 * 1024)
    cfg.backends.presets[name].live = True
    cap_ = world.runner.capacity
    assert cap_ is not None
    cap_.get(name)
    repo = next(iter(cfg.repos.repos))
    cfg.repos.repos[repo].backends = [name, cfg.routing.fallback]
    cfg.routing.tiers["claude-sonnet"] = name
    task = Task(
        task_id="pending-w1", repo=repo, base="main", why="w", value=1, risk=1,
        spec=Spec(goal="g", test_cmd="t", done_when="d", files_in_scope=["a.py"]),
    )  # fmt: skip
    r = route(task, cfg, context=cap_.route_context)
    assert r.preset == cfg.routing.fallback
    assert "tower context: estimated 60k > 56k budget (n_ctx 64k - 8k)" in r.tier_reason
    world.store.x("DELETE FROM model_calls")  # no history: 32k fits
    assert route(task, cfg, context=cap_.route_context).preset == name


def test_hosted_presets_ignore_the_budget(world: World) -> None:
    cap_ = Capacity(world.runner.cfg, Secrets({}), world.store, fetch=Props(1))
    name = next(iter(world.runner.cfg.backends.presets))
    world.runner.cfg.backends.presets[name].locality = "hosted"
    assert cap_.route_context(name) is None


def test_a_pool_change_is_picked_up_mid_queue(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world
    props = Props(4, 65536)
    now = [1000.0]
    _local(w, props, monkeypatch)
    w.runner.capacity = Capacity(
        w.runner.cfg, Secrets({}), w.store, fetch=props, clock=lambda: now[0]
    )
    w.runner.slot_gate = cap.SlotGate(w.runner.capacity)
    name = next(iter(w.runner.cfg.backends.presets))
    _call(w, "hist", name, 36 * 1024)
    gate = w.runner.slot_gate
    assert _take(w, name, "a")  # running
    waits = [0]

    def cancelled() -> bool:
        waits[0] += 1
        if waits[0] == 2:  # the owner enlarges the pool while "b" waits
            props.n_ctx = 131072
            now[0] += 61
        return waits[0] > 50

    assert gate.acquire(name, cancelled=cancelled, on_wait=lambda: None, poll=0.01, session_id="b")
    assert gate.live(name) == 2  # admitted while "a" still runs
    assert w.runner.capacity.get(name).n_ctx == 131072

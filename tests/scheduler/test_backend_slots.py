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

        def reserve(self, preset: str, budget: int | None) -> int:
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


def _call(
    w: World, sid: str, preset: str, tokens: int, *, ended: bool = True, status: str = "done"
) -> None:
    w.store.x(
        "INSERT OR IGNORE INTO sessions (id, role, status, created_at, ended_at, provenance)"
        " VALUES (?, 'worker', ?, 'now', ?, 'local')",
        (sid, status, "now" if ended else None),
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
    cap_._peaks.clear()  # the 60 s cache
    assert route(task, cfg, context=cap_.route_context).preset == name


def test_hosted_presets_ignore_the_budget(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = world.runner.cfg
    local = next(n for n in cfg.backends.presets if n != cfg.routing.fallback)
    _gate(world, 60 * 1024, monkeypatch)  # a local server too small for 60k sessions
    cap_ = world.runner.capacity
    assert cap_ is not None
    cap_.get(local)
    assert cap_.route_context(local) is not None  # the local preset is budgeted
    cfg.backends.presets[cfg.routing.fallback].locality = "hosted"
    assert cap_.route_context(cfg.routing.fallback) is None  # a hosted one is not
    from vigild.router.rules import route

    repo = next(iter(cfg.repos.repos))
    cfg.repos.repos[repo].backends = [local, cfg.routing.fallback]
    cfg.routing.tiers["claude-sonnet"] = cfg.routing.fallback
    r = route(_task(repo), cfg, context=cap_.route_context)
    assert r.preset == cfg.routing.fallback and "tower context" not in r.tier_reason


def _task(repo: str) -> Any:
    from vigild.contract.models import Spec, Task

    return Task(
        task_id="pending-w1", repo=repo, base="main", why="w", value=1, risk=1,
        spec=Spec(goal="g", test_cmd="t", done_when="d", files_in_scope=["a.py"]),
    )  # fmt: skip


def _too_big(w: World, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    cfg = w.runner.cfg
    name = next(n for n in cfg.backends.presets if n != cfg.routing.fallback)
    _gate(w, 0, monkeypatch)
    _call(w, "hist", name, 60 * 1024)
    cfg.backends.presets[name].live = True
    repo = next(iter(cfg.repos.repos))
    cfg.repos.repos[repo].backends = [name, cfg.routing.fallback]
    cfg.routing.tiers["claude-sonnet"] = name
    assert w.runner.capacity is not None
    w.runner.capacity.get(name)
    return name, repo


def test_a_private_repo_too_big_for_its_tower_is_blocked_never_hosted(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vigild.router.rules import RoutingError, route

    _, repo = _too_big(world, monkeypatch)
    cfg = world.runner.cfg
    cfg.backends.presets[cfg.routing.fallback].locality = "hosted"
    monkeypatch.setattr("vigild.router.rules.live_private", lambda r: True)
    monkeypatch.setattr("vigild.repos.live_private", lambda r: True)
    with pytest.raises(RoutingError, match="private"):
        route(_task(repo), cfg, context=world.runner.capacity.route_context)  # type: ignore[union-attr]


def test_the_min_task_cap_follows_the_rerouted_preset(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dispatch (`_under_minimum`) does not route again: it checks the preset stored at
    plan time, which is the re-routed one. The spec gate's `plan_min_cap` routes with the
    same context, so both name the fallback's minimum."""
    from vigild.contract.models import Size, WorkerContract

    name, repo = _too_big(world, monkeypatch)
    cfg = world.runner.cfg
    cfg.backends.presets[cfg.routing.fallback].min_task_usd = 5.0
    cfg.backends.presets[name].min_task_usd = None
    w_ = WorkerContract(
        task_id="pending-w1", goal="g", why="w", value=1, risk=1, test_cmd="t",
        done_when="d", files_in_scope=["a.py"], max_cost_usd=1.0, size=Size.S,
    )  # fmt: skip
    problem = world.runner.plan_min_cap(repo, "main", None, w_)
    assert problem is not None and cfg.routing.fallback in problem
    world.store.x("DELETE FROM model_calls")
    world.runner.capacity._peaks.clear()  # type: ignore[union-attr]
    assert world.runner.plan_min_cap(repo, "main", None, w_) is None  # stays on the tower


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


def test_two_waiters_that_fit_alone_are_not_both_admitted(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = _gate(world, 0, monkeypatch, n_ctx=98304)  # budget 90k, 32k each
    gate = world.runner.slot_gate
    cap_ = world.runner.capacity
    assert gate is not None and cap_ is not None
    assert _take(world, name, "x") and _take(world, name, "y")  # 64k held
    real = cap_.live_context

    def slow(sid: str) -> int:
        time.sleep(0.05)  # widen the window between the fit check and the admission
        return real(sid)

    monkeypatch.setattr(cap_, "live_context", slow)
    stop = threading.Event()
    got: dict[str, bool] = {}

    def waiter(sid: str) -> None:
        got[sid] = gate.acquire(
            name, cancelled=stop.is_set, on_wait=lambda: None, poll=0.01, session_id=sid
        )

    ts = [threading.Thread(target=waiter, args=(sid,)) for sid in ("b", "c")]
    for t in ts:
        t.start()
    time.sleep(0.4)  # both wait: 96k > 90k
    gate.release(name, "x")  # 32k + 32k + 32k fits only once more
    time.sleep(0.6)
    stop.set()
    for t in ts:
        t.join(5)
    assert sorted(got.values()) == [False, True]
    assert gate.live(name) == 2


def test_a_props_outage_keeps_the_last_good_pool_and_is_not_hammered(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = world
    props = Props(4, 65536)
    now = [1000.0]
    _local(w, props, monkeypatch)
    cap_ = Capacity(w.runner.cfg, Secrets({}), w.store, fetch=props, clock=lambda: now[0])
    name = next(iter(w.runner.cfg.backends.presets))
    assert cap_.budget(name) == 65536 - 8192
    props.fail = True
    before = len(props.calls)
    for _ in range(24):  # two minutes of waiting sessions, polling every 5 s
        now[0] += 5
        cap_.refresh_if_stale(name)
        assert cap_.budget(name) == 65536 - 8192  # the last good n_ctx, never None
        assert cap_.limits(name) == 4  # nor 1 slot
    assert len(props.calls) - before <= 3


def test_expected_peak_is_cached_for_60_seconds_and_the_index_migrates_twice(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from vigild import db

    w = world
    now = [1000.0]
    cap_ = Capacity(w.runner.cfg, Secrets({}), w.store, fetch=Props(4), clock=lambda: now[0])
    name = next(iter(w.runner.cfg.backends.presets))
    hits: list[str] = []
    real_q = w.store.q

    def counting(sql: str, params: Any = ()) -> Any:
        if "model_calls c" in sql:
            hits.append(sql)
        return real_q(sql, params)

    monkeypatch.setattr(w.store, "q", counting)
    for _ in range(5):
        cap_.expected_peak(name)
    assert len(hits) == 1
    now[0] += 61
    cap_.expected_peak(name)
    assert len(hits) == 2
    db.migrate(w.store.conn)
    db.migrate(w.store.conn)
    idx = w.store.q("SELECT name FROM sqlite_master WHERE type='index'")
    assert "calls_backend_preset" in {r["name"] for r in idx}


def test_a_failed_sessions_peak_counts(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    name = _gate(world, 0, monkeypatch)
    _call(world, "dead", name, 50 * 1024, ended=False, status="failed")
    assert world.runner.capacity.expected_peak(name) == 50 * 1024  # type: ignore[union-attr]

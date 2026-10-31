"""A local backend's capacity: how many sessions it can serve at once.

llama-server's `GET /props` says `total_slots` and, per slot,
`default_generation_settings.n_ctx`. vigild reads both (never hard-codes them),
caches them per preset, and records a `backend_capacity` event. A failed read
means ONE slot, never unlimited, and is not cached, so the next dispatch reads
again. `SlotGate` is the dispatch side: at most that many live sessions per
`locality: local` preset across every job; the rest wait, which is neither a
failure nor a page.

A local server's KV pool is shared (llama-server's `n_ctx` is the whole pool), so
the gate also budgets CONTEXT: the reservations of live sessions, each the larger
of the server's expected peak (the biggest prompt-plus-output of its last 20
finished sessions, floored at 32k) and the session's own latest call, must stay
within `n_ctx - 8192`. A session that would cross it queues like one that has no
slot; a task whose expected peak alone is over the budget is routed away
(`router.rules.route`).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx2

from vigild.config import Config, Preset, Secrets
from vigild.db import Store
from vigild.provenance import Provenance

log = logging.getLogger(__name__)

READ_TIMEOUT_SECONDS = 5.0
SLOT_POLL_SECONDS = 5.0  # how often a waiting session looks at its job

Fetch = Callable[[str, Mapping[str, str]], dict[str, Any]]


@dataclass(frozen=True)
class Slots:
    total_slots: int
    n_ctx: int | None  # per slot


def props_url(preset: Preset) -> str:
    """`<base_url without /v1>/props` (the same trim the gateway does)."""
    return preset.base_url.rstrip("/").removesuffix("/v1") + "/props"


class StatusError(Exception):
    """A /props answer that was not 200; its text is `HTTP <status>`, nothing else."""


def _fetch(url: str, headers: Mapping[str, str]) -> dict[str, Any]:
    with httpx2.Client(timeout=READ_TIMEOUT_SECONDS) as http:
        r = http.get(url, headers=dict(headers))
    if r.status_code != 200:
        raise StatusError(f"HTTP {r.status_code}")
    out = r.json()
    if not isinstance(out, dict):
        raise ValueError("not an object")
    return out


HEADROOM_TOKENS = 8192  # kept free of the KV pool for the sessions' growth
MIN_PEAK_TOKENS = 32768  # a session's expected peak is never reckoned lower
PEAK_HISTORY = 20  # finished sessions on a server the expected peak looks at

MAX_SLOTS = 64  # a ceiling on whatever a server claims
REFRESH_SECONDS = 60.0  # a waiting task re-reads /props at most this often
FAILURE_TTL_SECONDS = 30.0  # a failed read is remembered this long (as 1 slot)


class Capacity:
    def __init__(
        self,
        cfg: Config,
        secrets: Secrets,
        store: Store,
        *,
        fetch: Fetch | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.secrets = secrets
        self.store = store
        self._fetch = fetch or _fetch
        self._clock = clock
        self._cache: dict[str, Slots] = {}
        self._read_at: dict[str, float] = {}  # server -> when its cached answer was read
        self._failed: dict[str, float] = {}  # server -> when its failed read stops counting
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.Lock()  # guards the dicts only, never held over I/O

    def server(self, preset_name: str) -> str:
        """The server a preset lives on: its /props URL, normalized. Presets that
        share one share its slots."""
        return props_url(self.cfg.preset(preset_name)).lower()

    def limits(self, preset_name: str) -> int:
        return self.get(preset_name).total_slots

    def get(self, preset_name: str) -> Slots:
        """The cached capacity, read now if there is none. A failed read is
        1 slot, logged and recorded, and remembered for 30 s."""
        server = self.server(preset_name)
        with self._lock:
            hit = self._cache.get(server)
            if hit is not None:
                return hit
            if self._failed.get(server, 0.0) > self._clock():
                return Slots(1, None)
            lock = self._locks.setdefault(server, threading.Lock())
        with lock:  # one reader per server; the others wait for its answer
            with self._lock:
                hit = self._cache.get(server)
                if hit is not None:
                    return hit
                if self._failed.get(server, 0.0) > self._clock():
                    return Slots(1, None)
            got = self._read(preset_name)
            with self._lock:
                if got is None:
                    self._failed[server] = self._clock() + FAILURE_TTL_SECONDS
                    return Slots(1, None)
                self._cache[server] = got
                self._read_at[server] = self._clock()
                self._failed.pop(server, None)
                return got

    def refresh_if_stale(self, preset_name: str) -> None:
        """Re-read /props if the cached answer is 60 s old, so a pool the owner
        resized is picked up by a task already waiting. A failed read keeps its own
        30 s cache (as 1 slot)."""
        server = self.server(preset_name)
        with self._lock:
            at = self._read_at.get(server)
        if at is not None and self._clock() - at >= REFRESH_SECONDS:
            self.refresh(preset_name)

    def known(self, preset_name: str) -> Slots | None:
        """The cached capacity, never read: routing must not do I/O."""
        with self._lock:
            return self._cache.get(self.server(preset_name))

    def budget(self, preset_name: str) -> int | None:
        """`n_ctx - headroom`, or None while n_ctx is unknown. Reads live."""
        n_ctx = self.get(preset_name).n_ctx
        return None if n_ctx is None else max(0, n_ctx - HEADROOM_TOKENS)

    def expected_peak(self, preset_name: str) -> int:
        """The largest prompt-plus-output (`tokens_in + tokens_cache_read +
        tokens_out` of one call) seen in any of the last 20 finished sessions on the
        preset's server, floored at 32,768 (also the answer with no history). Not
        capped here: `route` compares it to the budget; `reserve` caps it."""
        server = self.server(preset_name)
        names = [n for n in self.cfg.backends.presets if self.server(n) == server]
        rows = self.store.q(
            "SELECT MAX(c.tokens_in + c.tokens_cache_read + c.tokens_out) AS peak"
            " FROM model_calls c JOIN sessions s ON s.id = c.session_id"
            " WHERE s.ended_at IS NOT NULL"
            " AND c.backend_preset IN (SELECT value FROM json_each(?))"
            " GROUP BY c.session_id ORDER BY MAX(c.id) DESC LIMIT ?",
            (json.dumps(names), PEAK_HISTORY),
        )
        return max([MIN_PEAK_TOKENS, *(int(r["peak"] or 0) for r in rows)])

    def reserve(self, preset_name: str) -> int:
        """What a new session reserves: the expected peak, capped at the budget."""
        peak = self.expected_peak(preset_name)
        budget = self.budget(preset_name)
        return peak if budget is None else min(peak, budget)

    def route_context(self, preset_name: str) -> tuple[int, int, int] | None:
        """`(expected peak, budget, n_ctx)` for the router, from the cached capacity
        only (no I/O); None when the preset is not local or n_ctx is not known."""
        if self.cfg.preset(preset_name).locality != "local":
            return None
        got = self.known(preset_name)
        if got is None or got.n_ctx is None:
            return None
        return self.expected_peak(preset_name), max(0, got.n_ctx - HEADROOM_TOKENS), got.n_ctx

    def live_context(self, session_id: str) -> int:
        """The session's latest call: prompt plus output tokens (0 before any)."""
        rows = self.store.q(
            "SELECT tokens_in + tokens_cache_read + tokens_out AS n FROM model_calls"
            " WHERE session_id=? ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        return int(rows[0]["n"]) if rows else 0

    def refresh(self, preset_name: str) -> Slots:
        server = self.server(preset_name)
        with self._lock:
            self._cache.pop(server, None)
            self._failed.pop(server, None)
        return self.get(preset_name)

    def start(self) -> None:
        """At vigild's start: read every live local preset's capacity once."""
        for name, p in self.cfg.backends.presets.items():
            if p.locality == "local" and p.live:
                self.get(name)

    def _read(self, preset_name: str) -> Slots | None:
        preset = self.cfg.preset(preset_name)
        key = self.secrets.get(preset.key_ref) if preset.key_ref else None
        headers = {"authorization": f"Bearer {key}"} if key else {}
        try:
            props = self._fetch(props_url(preset), headers)
            total = props["total_slots"]
            if not isinstance(total, int) or isinstance(total, bool) or total < 1:
                raise ValueError("total_slots is not an int >= 1")
            total = min(total, MAX_SLOTS)
            ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
            n_ctx = ctx if isinstance(ctx, int) and not isinstance(ctx, bool) else None
        except Exception as e:  # never the key: the class name, or the HTTP status
            why = str(e) if isinstance(e, StatusError) else type(e).__name__
            log.warning("%s: /props unreadable (%s); assuming 1 slot", preset_name, why)
            self._event("backend_capacity", {"preset": preset_name, "ok": False, "error": why,
                                             "total_slots": 1})  # fmt: skip
            return None
        self._event(
            "backend_capacity",
            {"preset": preset_name, "ok": True, "total_slots": total, "n_ctx": n_ctx},
        )
        return Slots(total, n_ctx)

    def _event(self, kind: str, data: dict[str, Any]) -> None:
        try:
            self.store.add_event(kind, data, Provenance.HUMAN)
        except Exception:
            log.exception("%s event failed", kind)


class SlotGate:
    """Live sessions per preset, held against the preset's capacity."""

    def __init__(self, capacity: Capacity) -> None:
        self.capacity = capacity
        self._cond = threading.Condition()
        self._live: dict[str, int] = {}
        self._held: dict[str, dict[str, int]] = {}  # server -> session -> its reservation
        self._anon = 0

    def reserved(self, preset: str) -> int:
        """The sum of the live sessions' reservations on the preset's server: each
        its admission-time expected peak, raised (never lowered) by its live context."""
        server = self.capacity.server(preset)
        with self._cond:
            held = dict(self._held.get(server, {}))
        return sum(max(r, self.capacity.live_context(sid)) for sid, r in held.items())

    def live(self, preset: str) -> int:
        preset = self.capacity.server(preset)
        with self._cond:
            return self._live.get(preset, 0)

    def acquire(
        self,
        preset: str,
        *,
        cancelled: Callable[[], bool],
        on_wait: Callable[[], None],
        poll: float | None = None,
        session_id: str | None = None,
    ) -> bool:
        """Take a slot, waiting while the preset is full by slots or by context (the
        reservations of the live sessions plus this one's expected peak must fit
        `n_ctx - 8192`; the first session always fits). `on_wait` runs once, when the
        wait begins. False when `cancelled()` ended the wait."""
        poll = SLOT_POLL_SECONDS if poll is None else poll
        waited = False
        name = preset
        preset = self.capacity.server(preset)  # presets on one server share its slots
        if session_id is None:
            with self._cond:
                self._anon += 1
                session_id = f"anon-{self._anon}"
        while True:
            if waited:
                self.capacity.refresh_if_stale(name)  # I/O, outside the condition
            limit = self.capacity.limits(name)
            budget = self.capacity.budget(name)
            need = self.capacity.reserve(name)
            used = self.reserved(name)
            with self._cond:
                n = self._live.get(preset, 0)
                if n < limit and (budget is None or n == 0 or used + need <= budget):
                    self._live[preset] = n + 1
                    self._held.setdefault(preset, {})[session_id] = need
                    self._budget_event(name, budget, need, used, "admitted")
                    return True
                if not waited:
                    waited = True
                    self._budget_event(name, budget, need, used, "queued")
                    on_wait()
                if cancelled():
                    return False
                self._cond.wait(timeout=poll)

    def _budget_event(
        self, preset: str, budget: int | None, need: int, used: int, outcome: str
    ) -> None:
        if budget is None:
            return
        n_ctx = budget + HEADROOM_TOKENS
        self.capacity._event(
            "context_budget",
            {"preset": preset, "outcome": outcome, "n_ctx": n_ctx, "headroom": HEADROOM_TOKENS,
             "budget": budget, "expected_peak": need, "reserved": used},
        )  # fmt: skip

    def release(self, preset: str, session_id: str | None = None) -> None:
        preset = self.capacity.server(preset)
        with self._cond:
            self._live[preset] = max(0, self._live.get(preset, 0) - 1)
            held = self._held.get(preset, {})
            if session_id is not None:
                held.pop(session_id, None)
            elif held:  # an unnamed release frees the oldest anonymous holder
                held.pop(next(iter(held)), None)
            self._cond.notify_all()

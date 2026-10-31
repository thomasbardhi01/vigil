"""A local backend's capacity: how many sessions it can serve at once.

llama-server's `GET /props` says `total_slots` and, per slot,
`default_generation_settings.n_ctx`. vigild reads both (never hard-codes them),
caches them per preset, and records a `backend_capacity` event. A failed read
means ONE slot, never unlimited, and is not cached, so the next dispatch reads
again. `SlotGate` is the dispatch side: at most that many live sessions per
`locality: local` preset across every job; the rest wait, which is neither a
failure nor a page.
"""

from __future__ import annotations

import logging
import threading
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


def _fetch(url: str, headers: Mapping[str, str]) -> dict[str, Any]:
    with httpx2.Client(timeout=READ_TIMEOUT_SECONDS) as http:
        r = http.get(url, headers=dict(headers))
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    out = r.json()
    if not isinstance(out, dict):
        raise ValueError("not an object")
    return out


class Capacity:
    def __init__(
        self, cfg: Config, secrets: Secrets, store: Store, *, fetch: Fetch | None = None
    ) -> None:
        self.cfg = cfg
        self.secrets = secrets
        self.store = store
        self._fetch = fetch or _fetch
        self._cache: dict[str, Slots] = {}
        self._lock = threading.Lock()

    def limits(self, preset_name: str) -> int:
        return self.get(preset_name).total_slots

    def get(self, preset_name: str) -> Slots:
        """The cached capacity, read now if there is none. A failed read is
        1 slot, logged and recorded, and not cached."""
        with self._lock:
            hit = self._cache.get(preset_name)
            if hit is not None:
                return hit
            got = self._read(preset_name)
            if got is not None:
                self._cache[preset_name] = got
                return got
            return Slots(1, None)

    def refresh(self, preset_name: str) -> Slots:
        with self._lock:
            self._cache.pop(preset_name, None)
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
            total = int(props["total_slots"])
            if total < 1:
                raise ValueError("total_slots < 1")
            ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
            n_ctx = int(ctx) if isinstance(ctx, int) and not isinstance(ctx, bool) else None
        except Exception as e:  # never the key: the class name only
            why = type(e).__name__
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

    def live(self, preset: str) -> int:
        with self._cond:
            return self._live.get(preset, 0)

    def acquire(
        self,
        preset: str,
        *,
        cancelled: Callable[[], bool],
        on_wait: Callable[[], None],
        poll: float | None = None,
    ) -> bool:
        """Take a slot, waiting while the preset is full. `on_wait` runs once, when
        the wait begins. False when `cancelled()` ended the wait."""
        poll = SLOT_POLL_SECONDS if poll is None else poll
        waited = False
        limit = self.capacity.limits(preset)  # outside the condition: it may do I/O
        while True:
            with self._cond:
                if self._live.get(preset, 0) < limit:
                    self._live[preset] = self._live.get(preset, 0) + 1
                    return True
                if not waited:
                    waited = True
                    on_wait()
                if cancelled():
                    return False
                self._cond.wait(timeout=poll)

    def release(self, preset: str) -> None:
        with self._cond:
            self._live[preset] = max(0, self._live.get(preset, 0) - 1)
            self._cond.notify_all()

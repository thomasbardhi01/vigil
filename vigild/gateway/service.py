"""The model gateway (P1, owner 2026-10-22).

Containers get a per-session gateway token, never a provider key. The
gateway:
- resolves the token to its session, repo and backend preset;
- enforces the private-repo backend rule on the wire, per call;
- refuses a model the repo's backends don't list, or one with no price;
- refuses a call whose worst case would take the session past its budget
  reservation, before the call is sent;
- injects the provider key and forwards;
- meters the call (tokens in, out, cache read, cache write; price-table cost;
  the provider's own cost if it reports one).

vigild's own model calls (the Haiku decider) go through `call()`, in process,
under the same checks plus a per-call reservation.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import math
import re
import secrets
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx2

from vigild.budget import Budget, BudgetExceeded
from vigild.config import Config, Preset, Secrets
from vigild.db import Store, iso, utcnow
from vigild.metering.calls import (
    CallUsage,
    SSEUsageTap,
    call_cost_by_key,
    record_call,
    usage_from_anthropic,
)
from vigild.metering.prices import PriceTable
from vigild.provenance import Provenance
from vigild.redact import redact
from vigild.repos import RepoPolicyError, check_backend, check_decider_route, live_private

FALLBACK_PURPOSE = "decider_fallback"  # a Haiku decision Jev couldn't give (owner ruling 4)

FORWARD_HEADERS = ("anthropic-version", "anthropic-beta", "content-type", "accept")
# Review round 1, item 5: only plain Messages requests pass. Server tools and
# MCP connectors would let Anthropic fetch from or post to hosts the session's
# proxy never allowed, and run up fees the gateway doesn't meter.
ALLOWED_BODY_KEYS = frozenset(
    {
        "model",
        "messages",
        "system",
        "max_tokens",
        "metadata",
        "stop_sequences",
        "stream",
        "temperature",
        "top_p",
        "top_k",
        "tools",
        "tool_choice",
        "thinking",
        "output_config",
        "context_management",
    }
)
CLIENT_TOOL_TYPES = re.compile(r"^(custom|bash_\d{8}|text_editor_\d{8}|memory_\d{8})$")
# Betas Claude Code 2.1.306 sends (observed through the gateway, 2026-10-22),
# plus the ones vigild's own calls use. Anything else is refused by name.
ALLOWED_BETAS = frozenset(
    {
        "claude-code-20250219",
        "interleaved-thinking-2025-05-14",
        "fine-grained-tool-streaming-2025-05-14",
        "context-management-2025-06-27",
        "prompt-caching-scope-2026-01-05",
        "effort-2025-11-24",
        # Also sent by CLI 2.1.306, seen at the gateway in the live guard test.
        # advanced-tool-use only matters with server tools, which _check_body refuses.
        "thinking-token-count-2026-05-13",
        "per-turn-control-2026-07-01",
        "mid-conversation-tool-changes-2026-07-01",
        "advanced-tool-use-2025-11-20",
        "thinking-display-updates-2026-08-18",
    }
)
# Review round 2, N4: content blocks are allowlisted at every level. A URL
# source would have Anthropic fetch a host the session's proxy never allowed;
# server-tool, MCP and search blocks carry content from tools vigild doesn't run.
# Thinking blocks are the model's own output, echoed back in assistant turns.
MESSAGE_BLOCKS = frozenset({"text", "image", "document", "tool_use", "tool_result"})
ASSISTANT_ONLY_BLOCKS = frozenset({"thinking", "redacted_thinking"})
# Owner decision 2026-10-22 (review round 3): thinking blocks are allowed, in
# assistant turns only, with exactly their own fields and nothing else.
THINKING_FIELDS = {
    "thinking": frozenset({"type", "thinking", "signature"}),
    "redacted_thinking": frozenset({"type", "data"}),
}
TOOL_RESULT_BLOCKS = frozenset({"text", "image", "document"})
SYSTEM_BLOCKS = frozenset({"text"})
SOURCED_BLOCKS = frozenset({"image", "document"})
# The CLI's own small-model side calls (titles, summaries) use this model; it is
# the one model a session may call besides its routed one, where the repo allows it.
SIDE_MODELS = frozenset({"claude-haiku-5-5"})
TOKEN_TTL_MARGIN_MIN = 15
METERED_PATHS = ("/v1/messages",)
FREE_PATHS = ("/v1/messages/count_tokens",)
CHARS_PER_TOKEN = 3  # deliberately low, so the input estimate errs high
DEFAULT_MAX_TOKENS = 4096
# An exact input count (count_tokens, /tokenize) must never stall the call path: after
# this long the hold falls back to chars / 3 (owner ruling R23, 2026-10-31 (#1)).
COUNT_TIMEOUT_S = 3.0
# The gateway clamps a call's max_tokens to the session cap and to what the
# session's remaining reservation affords; below this floor it refuses instead.
MIN_OUTPUT_TOKENS = 4096
# Thinking counts as output: its budget is clamped so this much of the
# (clamped) max_tokens is left for the answer, and Anthropic's own minimum
# thinking budget must still fit.
THINKING_ANSWER_ROOM = 4096
MIN_THINKING_BUDGET = 1024


def _find_ttls(x: Any, found: set[str]) -> None:
    if isinstance(x, dict):
        cc = x.get("cache_control")
        if isinstance(cc, dict):
            found.add(str(cc.get("ttl") or "5m"))
        for v in x.values():
            _find_ttls(v, found)
    elif isinstance(x, list):
        for v in x:
            _find_ttls(v, found)


def write_ttl(body: dict[str, Any]) -> str:
    """The cache TTL the request asks its writes to be billed at: `1h` if any
    `cache_control` in tools, system or messages asks for more than the provider's 5-minute
    default (an unknown value counts as 1h), else `5m`. A mixed request takes the dearest
    present, never a cheaper one than any it asked for."""
    found: set[str] = set()
    for k in ("tools", "system", "messages"):
        _find_ttls(body.get(k), found)
    return "5m" if found <= {"5m"} else "1h"


def input_usage(read: int, write: int, out: int, ttl: str) -> CallUsage:
    """`read` tokens at the cache-read rate, `write` at the write rate of `ttl`."""
    if ttl == "5m":
        return CallUsage(tokens_cache_read=read, tokens_cache_write_5m=write, tokens_out=out)
    return CallUsage(tokens_cache_read=read, tokens_cache_write_1h=write, tokens_out=out)


def worst_case_usd(
    prices: PriceTable, model: str, raw_len: int, max_out: int, cached_tokens: int = 0
) -> float:
    """The most a call could cost: every input token written to the 1-hour
    cache (the dearest input rate), plus max_out tokens of output. The first
    `cached_tokens` of the input (a prefix the session's previous call wrote,
    `Gateway._cached_prefix`) are priced at the cache-read rate instead (#79)."""
    est_in = math.ceil(raw_len / CHARS_PER_TOKEN)
    read = max(0, min(cached_tokens, est_in))
    return prices.cost(
        model,
        CallUsage(tokens_cache_read=read, tokens_cache_write_1h=est_in - read, tokens_out=max_out),
    )


# #79 (a): a session's next call usually resends the previous call's input, which the
# provider bills at the cache-read rate. The gateway prices it so in the worst case only
# when all of this holds: the session's previous call reported cached tokens (usage,
# never a request field); its input (tools, system, messages) is a hash-equal prefix of
# this one's; it finished within the TTL below.
PREFIX_TTL_S = 50 * 60
PREFIX_TTL_5M_S = 5 * 60  # a 5m request's cache entry lives five minutes
EPS = 1e-9


def _strip_cache_control(x: Any) -> Any:
    """`cache_control` markers move from call to call (the CLI marks the newest
    message); the provider's cache key ignores them, so the hash does too."""
    if isinstance(x, dict):
        return {k: _strip_cache_control(v) for k, v in x.items() if k != "cache_control"}
    if isinstance(x, list):
        return [_strip_cache_control(v) for v in x]
    return x


def prefix_digest(body: dict[str, Any], n: int) -> tuple[str, int]:
    """Hash and length (UTF-8 bytes, which `chars / 3` estimates tokens from) of the
    request's input up to its first `n`
    messages: the model and `thinking` setting (a change of either misses the
    provider's cache), tools, then system, then those messages, as compact sorted JSON without
    cache markers. This is the prefix the provider can cache, in its own order."""
    msgs = body.get("messages")
    part = [
        body.get("model"),
        body.get("thinking"),
        body.get("tools"),
        body.get("system"),
        msgs[:n] if isinstance(msgs, list) else [],
    ]
    text = json.dumps(
        _strip_cache_control(part), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    data = text.encode()
    return hashlib.sha256(data).hexdigest(), len(data)


@dataclass(frozen=True)
class PrefixRecord:
    """What a session's last finished call left in the provider's cache, as far as
    vigild knows: the hash of its whole input, how many messages that was, its
    length (characters), what its usage reported (owner ruling R23, 2026-10-31 (#1)):
    the prompt total (input + cache reads + cache writes) and the part of it in the
    provider's cache after the call (reads and writes; owner, 2026-11-01), and when."""

    digest: str
    messages: int
    chars: int
    cached_tokens: int
    at: float
    prompt_tokens: int = 0


UPSTREAM_READ_S = 600.0  # the longest an upstream call waits for its next bytes
UPSTREAM_TIMEOUT = httpx2.Timeout(UPSTREAM_READ_S, connect=10.0)
# a call in flight keeps its reservation live (2a round 9) until nothing of it
# has moved for the read timeout plus this: httpx has given up on it by then
LIVE_MARGIN_S = 120.0


def _refuse_block(where: str, why: str) -> GatewayError:
    return GatewayError(403, "permission_error", f"{where}: {why}")


def _check_blocks(blocks: Any, allowed: frozenset[str], where: str) -> None:
    if isinstance(blocks, str):
        return
    if not isinstance(blocks, list):
        raise GatewayError(400, "invalid_request_error", f"{where} must be a string or a list")
    for i, b in enumerate(blocks):
        at = f"{where}[{i}]"
        kind = b.get("type") if isinstance(b, dict) else None
        if kind not in allowed:
            raise _refuse_block(at, f"content block {kind!r} is not allowed")
        if kind in THINKING_FIELDS and set(b) - THINKING_FIELDS[kind]:
            extra = sorted(set(b) - THINKING_FIELDS[kind])
            raise _refuse_block(at, f"{kind} block fields not allowed: {extra}")
        if kind in SOURCED_BLOCKS:
            src = b.get("source")
            if not isinstance(src, dict) or src.get("type") != "base64":
                got = src.get("type") if isinstance(src, dict) else None
                raise _refuse_block(at, f"{kind} source {got!r} is not allowed; base64 only")
        if kind == "tool_result":
            _check_blocks(b.get("content", ""), TOOL_RESULT_BLOCKS, f"{at}.content")


def check_content(body: dict[str, Any]) -> None:
    """Walk `system` and every message's content (review round 2, N4)."""
    if "system" in body:
        _check_blocks(body["system"], SYSTEM_BLOCKS, "system")
    messages = body.get("messages", [])
    if not isinstance(messages, list):
        raise GatewayError(400, "invalid_request_error", "messages must be a list")
    for i, m in enumerate(messages):
        if not isinstance(m, dict):
            raise GatewayError(400, "invalid_request_error", f"messages[{i}] must be an object")
        allowed = MESSAGE_BLOCKS | (
            ASSISTANT_ONLY_BLOCKS if m.get("role") == "assistant" else set()
        )
        _check_blocks(m.get("content", ""), frozenset(allowed), f"messages[{i}].content")


log = logging.getLogger(__name__)
EXEMPT_OVERFLOWS = 10  # context-overflow 5xx in a row a local preset may answer with
CONTEXT_WORDS = ("context size", "context length", "context window", "context_overflow",
                 "prompt is too long", "too many tokens")  # fmt: skip


class GatewayError(Exception):
    def __init__(
        self,
        status: int,
        kind: str,
        message: str,
        *,
        reason: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason or message  # what the refusal event records
        self.extra = extra or {}
        self.status = status
        self.kind = kind
        self.message = message

    def body(self) -> dict[str, Any]:
        return {
            "type": "error",
            "error": {"type": self.kind, "message": f"vigil gateway: {self.message}"},
        }


@dataclass(frozen=True)
class GatewaySession:
    session_id: str
    repo: str
    preset: str
    task_id: str | None
    job_id: str | None
    model: str = ""
    private: bool = True  # read live when the token was issued (fail closed)


@dataclass
class Hold:
    """One in-flight call's worst case, held against its session until it settles."""

    session_id: str
    amount: float
    preset: Preset
    body: dict[str, Any]
    raw: bytes = b""  # what is forwarded: the request, with max_tokens clamped
    released: bool = False
    probe: str | None = None  # the backend breaker's half-open probe this call claimed
    cached_tokens: int = 0  # the input tokens the hold priced at the cache-read rate (#79)
    plain: float | None = None  # the same hold priced as a miss (day, month, metering failure)
    premium: float = 0.0  # plain - amount: held against the day and the month (R23)
    fingerprint: tuple[str, int, int] | None = None  # this input: digest, messages, chars
    # why the input was held as it was: prefix, count, estimate or task_miss
    reason: str = ""


class HeldStream:
    """A streamed response body whose call is booked and whose hold is released by
    `finish`, however the stream ends: read to the end, closed part-way, or never read
    (the client left before the first chunk; the response's background task calls
    `finish`)."""

    def __init__(self, gen: AsyncIterator[bytes], finish: Callable[[], Awaitable[None]]) -> None:
        self._gen = gen
        self.finish = finish

    def __aiter__(self) -> HeldStream:
        return self

    async def __anext__(self) -> bytes:
        return await self._gen.__anext__()

    async def aclose(self) -> None:
        close = getattr(self._gen, "aclose", None)
        try:
            if close is not None:
                await close()
        finally:
            await self.finish()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Gateway:
    def __init__(
        self,
        cfg: Config,
        store: Store,
        budget: Budget,
        secrets_: Secrets,
        *,
        transport: httpx2.BaseTransport | None = None,
        async_transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self.cfg = cfg
        self.store = store
        self.budget = budget
        self.secrets = secrets_
        self._exempt: dict[str, int] = {}  # preset -> context-overflow 5xx in a row
        self.prices = PriceTable(cfg.prices)
        self.sync_client = httpx2.Client(transport=transport, timeout=UPSTREAM_TIMEOUT)
        self.async_client = httpx2.AsyncClient(transport=async_transport, timeout=UPSTREAM_TIMEOUT)
        self._inflight: dict[str, float] = {}
        self._fallback_pending: dict[str, float] = {}  # repo -> held for fallback calls
        self._inflight_lock = threading.Lock()
        # set by the runner: stops the session's container (metering failed)
        self.stop_session: Callable[[str], None] | None = None
        self._drained = threading.Condition(self._inflight_lock)  # a session's holds all gone
        self._after_drain: dict[str, list[Callable[[], Any]]] = {}  # session -> settle
        self._seen: dict[str, float] = {}  # session -> when one of its calls last moved
        self._own: dict[int, float] = {}  # vigild's own call's reservation -> when it began
        self._now: Callable[[], float] = time.monotonic
        self._prefix: dict[str, PrefixRecord] = {}  # session -> its last call's cached input
        self._rereserve: dict[str, float] = {}  # session -> excess a cache miss still owes
        self._count_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=16, thread_name_prefix="vigil-count"
        )
        self._task_miss: set[str] = set()  # tasks (or sessions) held as full misses (R23)
        self._miss_checked: set[str] = set()  # tasks whose overshoot events were read
        # vigild's circuit breakers (plan 2a, item 4): every upstream answer
        # counts for or against the preset's backend breaker
        self.breakers: Any = None

    def _backend_gate(self, preset_name: str, session_id: str | None = None) -> str | None:
        """An open backend breaker refuses the call before it is sent, unless
        it has cooled down and this call claims its one half-open probe
        (review B6, A11). Returns the claimed scope, to release if the call
        never reaches upstream. A review replay (#47) never claims the probe: its
        result wouldn't count, so the breaker could stay half-open. It is refused,
        and the replay records that the gate refused it (owner, #49 round 2)."""
        if self.breakers is None:
            return None
        from vigild.breakers import Kind

        scope = f"backend:{preset_name}"
        if not self.breakers.is_open(Kind.BACKEND, scope):
            return None
        if self.store.is_replay(session_id):
            self.store.gate_refuse_replay(session_id, f"{preset_name}: backend breaker not closed")
            raise GatewayError(
                529,
                "overloaded_error",
                f"{preset_name}: backend breaker not closed (replay refused)",
            )
        if self.breakers.claim_probe(Kind.BACKEND, scope):
            return scope
        raise GatewayError(529, "overloaded_error", f"{preset_name}: its backend breaker is open")

    def _release_probe(self, scope: str | None) -> None:
        if scope is not None and self.breakers is not None:
            from vigild.breakers import Kind

            self.breakers.release_probe(Kind.BACKEND, scope)

    def _upstream(
        self, preset_name: str, ok: bool, detail: str = "", session_id: str | None = None
    ) -> None:
        """N 5xx or timeouts in a row trip the preset's backend breaker; any
        other answer ends the run (and closes a half-open one). A review replay
        (#47) never touches real breaker state, either way."""
        if self.breakers is None or self.store.is_replay(session_id):
            return
        from vigild.breakers import Kind

        scope = f"backend:{preset_name}"
        if ok:
            self.breakers.success(Kind.BACKEND, scope)
        else:
            self.breakers.failure(
                Kind.BACKEND, scope, self.cfg.vigild.breakers.backend_errors,
                {"preset": preset_name, "error": detail[:300]},
            )  # fmt: skip

    def _exempt_streak(self, preset_name: str, session_id: str | None) -> int:
        """One more context-overflow 5xx in a row from this local preset."""
        if self.store.is_replay(session_id):
            return 0
        self._exempt[preset_name] = self._exempt.get(preset_name, 0) + 1
        return self._exempt[preset_name]

    def _trip_overflow(self, preset_name: str, session_id: str | None) -> None:
        if self.breakers is None or self.store.is_replay(session_id):
            return
        from vigild.breakers import Kind

        self.breakers.trip(
            Kind.BACKEND, f"backend:{preset_name}",
            {"preset": preset_name, "error": "only context overflows",
             "in_a_row": self._exempt.get(preset_name, 0)},
        )  # fmt: skip

    # --- tokens -------------------------------------------------------------------

    def issue_token(self, session_id: str, repo: str, preset: str, *, ttl_minutes: int = 60) -> str:
        """A session's token: its repo, its preset's model, and a life of the
        session's own limit plus a margin (review round 1, item 7). The repo's
        visibility is read live here, at dispatch, and kept with the token for
        the session's per-call checks (owner, 2026-10-23)."""
        private = live_private(repo)
        check_backend(self.cfg, repo, preset, private=private)
        token = "vgw_" + secrets.token_urlsafe(32)
        expires = utcnow() + timedelta(minutes=ttl_minutes)
        self.store.x(
            "INSERT INTO gateway_tokens (token_hash, session_id, repo, backend_preset, model,"
            " created_at, expires_at, private) VALUES (?,?,?,?,?,?,?,?)",
            (
                _hash(token),
                session_id,
                repo,
                preset,
                self.cfg.preset(preset).model or "",
                iso(),
                iso(expires),
                int(private),
            ),
        )
        return token

    def revoke_all(self) -> int:
        """At startup: no token from before a restart survives it."""
        rows = self.store.q("SELECT COUNT(*) n FROM gateway_tokens WHERE revoked_at IS NULL")
        self.store.x("UPDATE gateway_tokens SET revoked_at=? WHERE revoked_at IS NULL", (iso(),))
        return int(rows[0]["n"])

    def revoke(self, session_id: str) -> None:
        self._prefix.pop(session_id, None)
        self._rereserve.pop(session_id, None)
        self.store.x(
            "UPDATE gateway_tokens SET revoked_at=? WHERE session_id=? AND revoked_at IS NULL",
            (iso(), session_id),
        )

    def authorize(self, token: str | None) -> GatewaySession:
        if not token:
            raise GatewayError(401, "authentication_error", "missing session token")
        rows = self.store.q(
            "SELECT g.session_id, g.repo, g.backend_preset, g.revoked_at, g.model, g.expires_at,"
            " g.private, s.task_id, s.job_id"
            " FROM gateway_tokens g LEFT JOIN sessions s ON s.id = g.session_id"
            " WHERE g.token_hash=?",
            (_hash(token),),
        )
        if not rows or rows[0]["revoked_at"]:
            raise GatewayError(401, "authentication_error", "invalid or revoked session token")
        r = rows[0]
        if r["expires_at"] and datetime.fromisoformat(r["expires_at"]) <= utcnow():
            raise GatewayError(401, "authentication_error", "session token expired")
        return GatewaySession(
            r["session_id"], r["repo"], r["backend_preset"], r["task_id"], r["job_id"], r["model"],
            private=r["private"] is None or bool(r["private"]),
        )  # fmt: skip

    # --- checks ---------------------------------------------------------------------

    def _preset(self, repo: str, preset_name: str, *, private: bool) -> Preset:
        try:
            check_backend(self.cfg, repo, preset_name, private=private)
        except RepoPolicyError as e:
            raise GatewayError(403, "permission_error", str(e)) from e
        preset = self.cfg.preset(preset_name)
        if preset.kind.value not in ("anthropic", "openai_compatible"):
            raise GatewayError(
                403, "permission_error", f"{preset.kind.value} backends arrive in a later phase"
            )
        return preset

    def _allowed_models(self, repo: str, provider: str) -> set[str]:
        pol = self.cfg.repo(repo)
        return {
            p.model
            for name in pol.backends
            if (p := self.cfg.backends.presets[name]).provider == provider and p.model
        }

    def _check_model(
        self, repo: str, preset: Preset, model: str | None, bound: str | None = None
    ) -> str:
        if not model:
            raise GatewayError(400, "invalid_request_error", "model is required")
        if bound and model != bound and model not in SIDE_MODELS:
            raise GatewayError(
                403, "permission_error", f"this session may call {bound}, not {model}"
            )
        if model not in self._allowed_models(repo, preset.provider):
            raise GatewayError(
                403,
                "permission_error",
                f"model {model} is not one {repo} may use (configs/repos.yaml)",
            )
        if not self.prices.has(model):
            raise GatewayError(403, "permission_error", f"model {model} has no price; refused")
        return model

    def worst_case(
        self, model: str, body: dict[str, Any], raw_len: int, cached_tokens: int = 0
    ) -> float:
        """The most a call could cost: every input token written to the 1-hour
        cache (the dearest input rate), plus max_tokens of output; the first
        `cached_tokens` at the cache-read rate."""
        max_out = int(body.get("max_tokens") or DEFAULT_MAX_TOKENS)
        return worst_case_usd(self.prices, model, raw_len, max_out, cached_tokens)

    def _match(self, session_id: str, body: dict[str, Any]) -> PrefixRecord | None:
        """The session's previous call, if this request starts with exactly its input: it
        finished within `PREFIX_TTL_S`, reported its usage, and its whole input (model,
        thinking, tools, system, messages) is by hash the start of this one's. Nothing the
        request claims about caching is read. Takes no lock."""
        rec = self._prefix.get(session_id)
        valid = PREFIX_TTL_5M_S if write_ttl(body) == "5m" else PREFIX_TTL_S  # 1h: 60 min, capped
        if rec is None or rec.prompt_tokens <= 0 or self._now() - rec.at > valid:
            return None
        msgs = body.get("messages")
        if not isinstance(msgs, list) or len(msgs) < rec.messages:
            return None
        if prefix_digest(body, rec.messages)[0] != rec.digest:
            return None
        return rec

    def _task_is_miss(self, session_id: str, task_id: str | None) -> bool:
        """After an overshoot every later call on the task is held as a miss (R23). The
        flag is kept in memory and re-read once per task from the overshoot events, so a
        restart does not lose it. Called under `_inflight_lock`."""
        key = task_id or session_id
        if key in self._task_miss:
            return True
        if task_id and task_id not in self._miss_checked:
            self._miss_checked.add(task_id)
            if self.store.q(
                "SELECT 1 FROM events WHERE task_id=? AND type='settle_excess'"
                " AND json_extract(data,'$.reason') IN ('cache_miss','estimate_low') LIMIT 1",
                (task_id,),
            ):
                self._task_miss.add(key)
                return True
        return False

    def _input_tokens(
        self, session_id: str, task_id: str | None, rec: PrefixRecord | None, chars: int,
        counted: int | None, raw_len: int,
    ) -> tuple[int, int, str]:  # fmt: skip
        """(tokens held at the read rate, tokens held at the write rate, why) for a call's
        input (R23). A prefix that matches the session's last *completed* call is that
        call's reported prompt total; the part it reported as cached (reads and writes) is
        held at the read rate whether or not another call of the session is in flight
        (owner, 2026-11-01: vi-0019 A1, step a), unless its task has overshot; the rest,
        and the bytes appended since (what a call in flight is still writing among them),
        at the write rate (the tail estimated at chars / 3). With no match the provider's
        own count, else chars / 3, all at the write rate. A miss goes through the
        overshoot path (`_learn`). Called under `_inflight_lock`."""
        if rec is None:
            if counted is not None:
                return 0, counted, "count"
            return 0, math.ceil(raw_len / CHARS_PER_TOKEN), "estimate"
        tail = math.ceil(max(0, chars - rec.chars) / CHARS_PER_TOKEN)
        if self._task_is_miss(session_id, task_id):
            return 0, rec.prompt_tokens + tail, "task_miss"
        read = min(rec.cached_tokens, rec.prompt_tokens)
        return read, rec.prompt_tokens - read + tail, "prefix"

    def _may_afford(self, session_id: str, model: str, want: int) -> bool:
        """The cheap pre-check before an exact count (which spends the shared key's
        `count_tokens` rate): the session has room for at least the output floor with no
        input at all, or is a reviewer or auditor whose reservation may grow. A session
        that fails it is refused by `_hold_clamped` anyway, counted or not."""
        if self._over_cap_role(session_id):
            return True
        with self._inflight_lock:
            headroom = self.budget.session_headroom(session_id) - self._inflight.get(
                session_id, 0.0
            )
        floor = self.prices.cost(model, CallUsage(tokens_out=min(want, MIN_OUTPUT_TOKENS)))
        return headroom >= floor

    def _fallback(self, gs: GatewaySession, preset_name: str, reason: str) -> None:
        try:  # the record never breaks the call
            self.store.add_event(
                "hold_estimate_fallback",
                {"preset": preset_name, "reason": reason},
                Provenance.HUMAN,
                job_id=gs.job_id,
                session_id=gs.session_id,
                task_id=gs.task_id,
            )
        except Exception:
            log.exception("could not record hold_estimate_fallback for %s", gs.session_id)

    def _count_input(
        self, gs: GatewaySession, preset: Preset, body: dict[str, Any], headers: dict[str, str]
    ) -> int | None:
        """The exact input tokens of a request, from the backend's own counter, through the
        same upstream client: Anthropic's free `/v1/messages/count_tokens`, llama-server's
        `/tokenize` (the request's text; JSON syntax makes it count a little high).
        OpenRouter has none. None, after a `hold_estimate_fallback` event (preset and
        reason, never the body), if there is no counter, it fails, or it is slower than
        `COUNT_TIMEOUT_S`: the caller then holds chars / 3."""
        kind = preset.kind.value
        if kind == "anthropic":
            path = "/v1/messages/count_tokens"
            payload: dict[str, Any] = {
                k: body[k]
                for k in ("model", "system", "messages", "tools", "tool_choice", "thinking")
                if k in body
            }
        elif kind == "openai_compatible":
            path = "/tokenize"
            text = {k: body[k] for k in ("system", "tools", "messages") if k in body}
            payload = {"content": json.dumps(text, ensure_ascii=False)}
        else:
            self._fallback(gs, gs.preset, "no_count_endpoint")
            return None
        fut: concurrent.futures.Future[httpx2.Response] | None = None
        try:
            url = self._upstream_url(preset, path)
            hdrs = self._headers(headers, self._key(preset), preset)
            content = json.dumps(payload).encode()
            # one total deadline, not httpx's per-phase timeouts: a slow-dripping counter
            # is abandoned (its thread ends on the per-phase limits) and the hold falls back
            fut = self._count_pool.submit(
                self.sync_client.post, url, headers=hdrs, content=content, timeout=COUNT_TIMEOUT_S
            )
            r = fut.result(timeout=COUNT_TIMEOUT_S)
        except GatewayError:
            self._fallback(gs, gs.preset, "no_key")
            return None
        except TimeoutError, httpx2.TimeoutException:
            if fut is not None:
                fut.cancel()  # not yet started: never starts
            self._fallback(gs, gs.preset, "timeout")
            return None
        except httpx2.HTTPError as e:
            self._fallback(gs, gs.preset, f"transport_{type(e).__name__}")
            return None
        if r.status_code != 200:
            self._fallback(gs, gs.preset, f"http_{r.status_code}")
            return None
        try:
            data = r.json()
            n = int(data["input_tokens"]) if kind == "anthropic" else len(data["tokens"])
        except Exception:
            n = 0
        if n < 1:
            self._fallback(gs, gs.preset, "bad_response")
            return None
        return n

    def _learn(self, hold: Hold, gs: GatewaySession, usage: CallUsage, cost: float) -> None:
        """After a session call is booked: remember its reported usage (the next call's
        prefix is counted from it, R23). If the hold was priced below its worst case and
        the call cost more than the hold, it is an overshoot (a cache miss; owner ruling
        R23, 2026-10-31 (#1)). Its real cost is already the session's (settle books the
        metered sum, uncapped); it is recorded as `settle_excess` with reason
        `cache_miss`, trips no breaker, pages the owner, makes every later call on the task
        a held miss, and the session's next call must first re-reserve the excess
        (`_hold_clamped`)."""
        # what the provider holds after this call: its reads and its writes (owner, 2026-11-01)
        cached = usage.tokens_cache_read + usage.tokens_cache_write_5m + usage.tokens_cache_write_1h
        prompt = usage.tokens_in + cached
        fp = hold.fingerprint
        if fp is not None and prompt > 0:
            self._prefix[gs.session_id] = PrefixRecord(
                fp[0], fp[1], fp[2], cached, self._now(), prompt
            )
        else:
            self._prefix.pop(gs.session_id, None)
        excess = cost - hold.amount
        if excess > EPS:  # any call over its task hold, however it was priced (R23, rule 5)
            reason = "cache_miss" if hold.premium > EPS else "estimate_low"
            # reserve the excess at once, in the same step that gives the premium back, so
            # open_today / open_month never drop below the true spend; if the caps refuse
            # it, the session owes it and its next call must re-reserve first (#79)
            reserved = self.budget.swap_premium(
                gs.session_id, hold.premium, task_id=gs.task_id, excess=excess,
                purpose="cache_miss_rereserve",
            )  # fmt: skip
            hold.premium = 0.0
            with self._inflight_lock:
                if not reserved:
                    self._rereserve[gs.session_id] = (
                        self._rereserve.get(gs.session_id, 0.0) + excess
                    )
                self._task_miss.add(gs.task_id or gs.session_id)
            self.store.add_event(
                "settle_excess",
                {"reason": reason, "session_id": gs.session_id, "task_id": gs.task_id,
                 "reserved_usd": round(hold.amount, 6), "reported_usd": round(cost, 6),
                 "hold_usd": round(hold.amount, 6), "actual_usd": round(cost, 6),
                 "excess_usd": round(excess, 6), "priced_as_read_tokens": hold.cached_tokens,
                 "read_tokens": usage.tokens_cache_read, "ruling": "R23"},
                Provenance.HUMAN,
                job_id=gs.job_id,
                session_id=gs.session_id,
                task_id=gs.task_id,
            )  # fmt: skip
            if not self.store.is_replay(gs.session_id):
                self.store.create_inbox_item(
                    "questions",
                    "page",
                    gs.job_id,
                    f"gateway hold overshoot: task {gs.task_id or gs.session_id} spent "
                    f"${cost:.4f} against a ${hold.amount:.4f} hold",
                    {"job_id": gs.job_id, "task_id": gs.task_id, "session_id": gs.session_id,
                     "hold_usd": round(hold.amount, 6), "actual_usd": round(cost, 6),
                     "excess_usd": round(excess, 6),
                     "note": f"{reason}: the call cost more than its task hold. Every later "
                     "call on this task is held as a full miss (owner ruling R23, "
                     "2026-10-31 (#1))",
                     "resumable": False},
                )  # fmt: skip

    def _rereserve_miss(self, session_id: str, task_id: str | None) -> None:
        """A cache miss spent more than its hold covered: before the session's next
        call, reserve that excess under the same caps as any reservation (the task's
        $2, the day, the month). Refused with the normal budget message if it does
        not fit, and the session stays refused. Called under `_inflight_lock`."""
        owed = self._rereserve.get(session_id, 0.0)
        if owed <= EPS:
            return
        try:
            self.budget.reserve(
                session_id=session_id, task_id=task_id, amount=owed, purpose="cache_miss_rereserve"
            )
        except BudgetExceeded as e:
            raise GatewayError(403, "permission_error", f"budget: {e}") from e
        self._rereserve.pop(session_id, None)

    def _hold_clamped(
        self,
        session_id: str,
        model: str,
        body: dict[str, Any],
        raw: bytes,
        *,
        task_id: str | None = None,
        info: dict[str, Any] | None = None,
        gs: GatewaySession | None = None,
        preset: Preset | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[float, dict[str, Any], bytes]:
        """Hold the call's worst case, clamping max_tokens (and a thinking
        budget) to the session cap and to what the reservation affords. Refuses
        below the floor, naming the cap. Returns the hold, the body and the
        raw bytes to forward.

        Owner ruling R23, 2026-10-31 (#1): the hold against the session's reservation (the
        task's) is the precise one (`_input_tokens`); the all-miss price of the same call
        is held too, its difference (the premium) against the day and the month, so those
        stay hard. Writes are held at the rate of the TTL the request asks for."""
        cap = self.cfg.budgets.session_max_output_tokens
        want = min(int(body.get("max_tokens") or DEFAULT_MAX_TOKENS), cap)
        th = body.get("thinking")
        thinking = isinstance(th, dict) and th.get("type") == "enabled" and "budget_tokens" in th
        ttl = write_ttl(body)
        msgs = body.get("messages")
        fp: tuple[str, int, int] | None = None
        if isinstance(msgs, list):
            digest, n_chars = prefix_digest(body, len(msgs))
            fp = (digest, len(msgs), n_chars)
        chars = fp[2] if fp else 0
        rec = self._match(session_id, body)
        counted = None
        if (
            rec is None
            and gs is not None
            and preset is not None
            and self._may_afford(session_id, model, want)
        ):
            counted = self._count_input(gs, preset, body, headers or {})  # not under the lock
        with self._inflight_lock:
            # A kill revokes, then drains, then settles; a call that passed `authorize`
            # before the revoke must not place its hold (or grow a reservation) after
            # the drain. Checked under the lock the drain waits on (#60).
            if self.store.q(
                "SELECT 1 FROM gateway_tokens WHERE session_id=? GROUP BY session_id"
                " HAVING SUM(revoked_at IS NULL) = 0",
                (session_id,),
            ):
                raise GatewayError(401, "authentication_error", "invalid or revoked session token")
            self._rereserve_miss(session_id, task_id)  # a cache miss owes a reservation (#79)
            read, write, why = self._input_tokens(
                session_id, task_id, rec, chars, counted, len(raw)
            )

            def price(o: int, miss: bool = False) -> float:
                if miss:
                    return self.prices.cost(model, input_usage(0, read + write, o, ttl))
                return self.prices.cost(model, input_usage(read, write, o, ttl))

            held = self._inflight.get(session_id, 0.0)
            headroom = self.budget.session_headroom(session_id) - held
            need = price(want)
            if need > headroom and self._over_cap_ok(session_id, need - headroom):
                headroom = need
            out = want
            # step down until the worst case fits (long-context rates make the
            # price per token depend on the input, so search rather than divide)
            while out > 0 and price(out) > headroom:
                out = min(out - 1, int(out * 0.98))
            if out < min(want, MIN_OUTPUT_TOKENS):
                raise GatewayError(
                    403,
                    "permission_error",
                    f"budget: this session's output cap is {cap} tokens per call; after "
                    f"this call's input the session has ${headroom:.4f} of its reservation "
                    f"left after calls in flight, enough for {max(out, 0)} output tokens, "
                    f"under the {MIN_OUTPUT_TOKENS}-token floor",
                )
            if thinking and out - THINKING_ANSWER_ROOM < MIN_THINKING_BUDGET:
                raise GatewayError(
                    403,
                    "permission_error",
                    f"budget: thinking needs {MIN_THINKING_BUDGET} tokens plus "
                    f"{THINKING_ANSWER_ROOM} for the answer, but this call may output only "
                    f"{out} (session cap {cap})",
                )
            amount = price(out)
            plain = price(out, True)
            premium = max(0.0, plain - amount)
            try:
                self.budget.hold_premium(session_id, premium)
            except BudgetExceeded as e:
                raise GatewayError(403, "permission_error", f"budget: {e}") from e
            if info is not None:
                info.update(
                    cached_tokens=read, plain=plain, premium=premium, fingerprint=fp, reason=why
                )
            self._inflight[session_id] = held + amount
            self._seen[session_id] = self._now()
        changed = out != body.get("max_tokens")
        body = {**body, "max_tokens": out}
        if thinking and int(th["budget_tokens"]) > out - THINKING_ANSWER_ROOM:  # type: ignore[index]
            body["thinking"] = {**th, "budget_tokens": out - THINKING_ANSWER_ROOM}  # type: ignore[dict-item]
            changed = True
        return amount, body, json.dumps(body).encode() if changed else raw

    def _check_body(self, body: dict[str, Any], headers: dict[str, str]) -> None:
        extra = sorted(set(body) - ALLOWED_BODY_KEYS)
        if extra:
            raise GatewayError(403, "permission_error", f"request fields not allowed: {extra}")
        mt = body.get("max_tokens", DEFAULT_MAX_TOKENS)
        if isinstance(mt, bool) or not isinstance(mt, int) or mt < 1:
            raise GatewayError(400, "invalid_request_error", "max_tokens must be an integer >= 1")
        check_content(body)
        for tool in body.get("tools") or []:
            kind = tool.get("type") if isinstance(tool, dict) else None
            if kind is not None and not CLIENT_TOOL_TYPES.match(str(kind)):
                raise GatewayError(403, "permission_error", f"server tool {kind} is not allowed")
        betas = [b.strip() for b in headers.get("anthropic-beta", "").split(",") if b.strip()]
        refused = [b for b in betas if b not in ALLOWED_BETAS]
        if refused:
            raise GatewayError(403, "permission_error", f"betas not allowed: {refused}")

    def _touch(self, session_id: str) -> None:
        """A streamed call's bytes arrived: it is alive (2a round 9)."""
        self._seen[session_id] = self._now()

    def holds(self, session_id: str | None, reservation_id: int) -> bool:
        """Whether a call is still in flight against this reservation (2a
        round 9): one of the session's calls, a settle waiting for one, or
        vigild's own call. Bounded: a call nothing of which has moved for the
        upstream read timeout plus a margin is over, whatever its hold says.
        The runner's liveness rule asks this first."""
        stale = self._now() - (UPSTREAM_READ_S + LIVE_MARGIN_S)
        with self._inflight_lock:
            if reservation_id in self._own:
                return self._own[reservation_id] > stale
            if session_id and (session_id in self._inflight or session_id in self._after_drain):
                return self._seen.get(session_id, 0.0) > stale
        return False

    def _over_cap_role(self, session_id: str) -> bool:
        """Whether the session may go past its cap (a reviewer or auditor, not a replay)."""
        from vigild.jobs.model import Role

        if self.store.is_replay(session_id):
            return False  # a replay's cap (review_session_usd) is hard (#47)
        try:
            role = self.store.get_session(session_id).role
        except KeyError:
            return False
        return role in (Role.REVIEWER, Role.AUDITOR)

    def _over_cap_ok(self, session_id: str, shortfall: float) -> bool:
        """A reviewer or auditor call past its session cap goes on (owner,
        2026-10-23): its reservation grows by the shortfall, against the day
        and the month, which stay hard stops. Any other session's cap is its
        cap. Raises GatewayError when the day or month can't take it."""
        if not self._over_cap_role(session_id):
            return False
        try:
            self.budget.reserve(
                session_id=session_id, task_id=None, amount=shortfall, purpose="review_over_cap"
            )
        except BudgetExceeded as e:
            raise GatewayError(403, "permission_error", f"budget: {e}") from e
        return True

    def _release_late(self, fut: asyncio.Future[Hold]) -> None:
        """A preflight finished after its request was cancelled: nobody will use its hold."""
        if fut.cancelled() or fut.exception() is not None:
            return  # a refusal placed nothing (and its exception is now retrieved)
        hold = fut.result()
        self._release_probe(hold.probe)  # a half-open probe it claimed goes back too
        self.release(hold)

    async def _abandon(self, hold: Hold, resp: httpx2.Response) -> None:
        """The request was cancelled while its response body was being read: close the
        response and give back the hold, its premium and any half-open probe."""
        try:
            await resp.aclose()
        finally:
            self._release_probe(hold.probe)
            self.release(hold)

    def release(self, hold: Hold) -> None:
        if hold.released:
            return
        hold.released = True
        self.budget.release_premium(hold.session_id, hold.premium)
        with self._inflight_lock:
            left = self._inflight.get(hold.session_id, 0.0) - hold.amount
            if left > 1e-12:
                self._inflight[hold.session_id] = left
            else:
                self._inflight.pop(hold.session_id, None)
                self._seen.pop(hold.session_id, None)
                self._drained.notify_all()
                later = self._after_drain.pop(hold.session_id, [])
        for fn in later if left <= 1e-12 else []:
            fn()  # a settle the runner left for when the late call was booked

    def after_drain(self, session_id: str, fn: Callable[[], Any]) -> None:
        """Run `fn` once none of the session's calls is in flight: now if
        none is, else when the last one is booked (2a round 8: a call that
        outlives the drain timeout still lands in the ledger, and the
        session's reservation stays open, and counted, until then)."""
        with self._inflight_lock:
            if session_id in self._inflight:
                self._after_drain.setdefault(session_id, []).append(fn)
                return
        fn()

    def drain(self, session_id: str, timeout: float = 60.0) -> bool:
        """Wait until none of the session's calls is in flight (each is booked
        before its hold goes), so settling sees every call's cost. A killed
        worker's last streamed call can finish after its container is gone
        (2a round 2, found by the done-when). False if the wait timed out."""
        with self._drained:
            return self._drained.wait_for(lambda: session_id not in self._inflight, timeout=timeout)

    def _record_or_fail_closed(self, hold: Hold, gs: GatewaySession, **kw: Any) -> None:
        """Record a finished upstream call. If that fails the call's spend is
        unknown: stop the session, book the worst case, page the owner."""
        try:
            cost = self._record(gs=gs, hold=hold, **kw)
        except Exception as e:
            self._metering_failed(hold, gs, kw["model"], kw["usage"], e)
            return
        try:
            self._learn(hold, gs, kw["usage"], cost)
        except Exception:
            log.exception("cache-prefix bookkeeping failed for %s", gs.session_id)

    def _metering_failed(
        self, hold: Hold, gs: GatewaySession, model: str, usage: CallUsage, err: Exception
    ) -> None:
        """Fail closed. Each step is tried even if an earlier one fails."""
        log.error("metering failed for session %s: %s", gs.session_id, err)
        call_id = f"{gs.session_id}:{secrets.token_hex(4)}"
        reason = redact(f"{type(err).__name__}: {err}")
        replay = self.store.is_replay(gs.session_id)  # a replay files no inbox item (#47)
        booked = hold.plain if hold.plain is not None else hold.amount  # never the cheaper hold
        steps: list[Callable[[], Any]] = [
            lambda: self.revoke(gs.session_id),  # no further call is forwarded
            lambda: self.budget.book_unmetered(gs.session_id, gs.task_id, booked),
            lambda: self.store.update_session(gs.session_id, status="failed"),
            lambda: self.store.add_event(
                "metering_failed",
                {"session_id": gs.session_id, "call_id": call_id, "error": reason},
                Provenance.HUMAN,
                job_id=gs.job_id,
                session_id=gs.session_id,
                task_id=gs.task_id,
            ),
            lambda: (
                replay
                or self.store.create_inbox_item(
                    "questions",
                    "page",
                    gs.job_id,
                    f"metering failed: {reason}; spend for call {call_id} not booked",
                    {
                        "session_id": gs.session_id,
                        "call_id": call_id,
                        "model": model,
                        "tokens_in": usage.tokens_in,
                        "tokens_out": usage.tokens_out,
                        "tokens_cache_read": usage.tokens_cache_read,
                        "tokens_cache_write_5m": usage.tokens_cache_write_5m,
                        "tokens_cache_write_1h": usage.tokens_cache_write_1h,
                        "booked_usd": booked,
                        "note": "the call's worst-case reservation was booked as spent; "
                        "reconcile with the provider's usage",
                        "resumable": False,
                    },
                )
            ),
            lambda: self.stop_session(gs.session_id) if self.stop_session else None,
        ]
        for step in steps:
            try:
                step()
            except Exception:
                log.exception("metering-failure step failed for %s", gs.session_id)

    def _key(self, preset: Preset) -> str:
        key = self.secrets.get(preset.key_ref)
        if not key:
            raise GatewayError(503, "api_error", f"{preset.key_ref} is not set in the env file")
        return key

    def _upstream_error(self, gs: GatewaySession, data: dict[str, Any]) -> None:
        """The backend's own failure for a session's call, which has no
        `model_calls` row: `{status, type?, code?, context, model}` for an HTTP
        status, `{transport}` for a transport error class. No free text. A page's
        `cause` is read from it (#181). It never breaks the call it records."""
        try:
            self.store.add_event(
                "upstream_error", data, Provenance.HUMAN,
                job_id=gs.job_id, session_id=gs.session_id, task_id=gs.task_id,
            )  # fmt: skip
        except Exception:
            log.exception("upstream_error event failed for %s", gs.session_id)

    @staticmethod
    def _http_failure(status: int, body: bytes) -> dict[str, Any]:
        """Only what the cause needs from a backend's error body: its type and
        code (64 characters each, redacted) and two flags computed here."""
        text = body[:4000].decode(errors="replace")
        low = text.lower()
        out: dict[str, Any] = {
            "status": status,
            "context": any(w in low for w in CONTEXT_WORDS),
            "model": "model" in low and ("not found" in low or "not_found" in low),
        }
        try:
            err = json.loads(text).get("error")
        except ValueError, AttributeError:
            err = None
        if isinstance(err, dict):
            for k in ("type", "code"):
                v = err.get(k)
                if isinstance(v, str | int) and not isinstance(v, bool):
                    out[k] = str(redact(str(v)))[:64]
        return out

    def _is_hosted_model(self, model: str) -> bool:
        return self.prices.has(model) or any(
            p.locality == "hosted" and p.model == model for p in self.cfg.backends.presets.values()
        )

    def _check_locality(self, gs: GatewaySession, preset: Preset, model: object) -> None:
        """A session on a `locality: local` preset makes no hosted call (#197).
        Locality is the session's own preset in `configs/backends.yaml`, read here,
        never from the request; the refusal precedes any hold, so nothing is metered."""
        if preset.locality != "local" or not isinstance(model, str) or not model:
            return
        if not self._is_hosted_model(model) or model == preset.model:
            return
        msg = (
            f"{model} is a hosted model; a session on the local preset {gs.preset} may not call it"
        )
        raise GatewayError(
            403,
            "permission_error",
            msg,
            reason="hosted_model_for_local_session",
            extra={"model": model, "preset": gs.preset},
        )

    def _refuse(self, gs: GatewaySession, err: GatewayError) -> GatewayError:
        self.store.add_event(
            "gateway_refused",
            redact(
                {"status": err.status, "reason": err.reason, "message": err.message, **err.extra}
            ),
            Provenance.HUMAN,
            job_id=gs.job_id,
            session_id=gs.session_id,
            task_id=gs.task_id,
        )
        return err

    def preflight(
        self, gs: GatewaySession, path: str, raw: bytes, headers: dict[str, str] | None = None
    ) -> Hold:
        if path not in METERED_PATHS + FREE_PATHS:
            raise GatewayError(404, "not_found_error", f"{path} is not served")
        try:
            preset = self._preset(gs.repo, gs.preset, private=gs.private)
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError as e:
                raise GatewayError(400, "invalid_request_error", "body is not JSON") from e
            if not isinstance(body, dict):
                raise GatewayError(400, "invalid_request_error", "body must be an object")
            self._check_body(body, headers or {})
            self._check_locality(gs, preset, body.get("model"))
            model = self._check_model(gs.repo, preset, body.get("model"), gs.model or None)
            amount = 0.0
            info: dict[str, Any] = {}
            if path in METERED_PATHS:
                amount, body, raw = self._hold_clamped(
                    gs.session_id, model, body, raw, task_id=gs.task_id, info=info,
                    gs=gs, preset=preset, headers=headers,
                )  # fmt: skip
            try:
                probe = self._backend_gate(
                    gs.preset, gs.session_id
                )  # last: nothing refuses after a claim
            except GatewayError:
                if amount:
                    self.release(
                        Hold(gs.session_id, amount, preset, body, raw, premium=info["premium"])
                    )
                raise
        except GatewayError as e:
            raise self._refuse(gs, e) from None
        return Hold(
            gs.session_id, amount, preset, body, raw, probe=probe,
            cached_tokens=info.get("cached_tokens", 0), plain=info.get("plain"),
            premium=info.get("premium", 0.0), fingerprint=info.get("fingerprint"),
            reason=info.get("reason", ""),
        )  # fmt: skip

    # --- forwarding ------------------------------------------------------------------

    @staticmethod
    def _upstream_url(preset: Preset, path: str) -> str:
        """The one place a preset's base_url meets a request path. An
        openai_compatible base_url ends in /v1, and the path begins with it."""
        base = preset.base_url.rstrip("/")
        if preset.kind.value == "openai_compatible":
            base = base.removesuffix("/v1")
        return base + path

    def _headers(self, incoming: dict[str, str], key: str, preset: Preset) -> dict[str, str]:
        out = {h: incoming[h] for h in FORWARD_HEADERS if h in incoming}
        out.setdefault("anthropic-version", "2023-06-01")
        out.setdefault("content-type", "application/json")
        if preset.kind.value == "openai_compatible":  # llama-server: bearer, not x-api-key
            out["authorization"] = f"Bearer {key}"
        else:
            out["x-api-key"] = key
        return out

    def _record(
        self,
        *,
        gs: GatewaySession | None,
        preset_name: str,
        preset: Preset,
        model: str,
        usage: CallUsage,
        started: float,
        purpose: str,
        job_id: str | None = None,
        provider_cost: float | None = None,
        stop_reason: str | None = None,
        repo: str | None = None,
        call_key: str | None = None,
        hold: Hold | None = None,
    ) -> float:
        truncated = stop_reason == "max_tokens"
        if truncated and gs:
            self.store.add_event(
                "call_truncated",
                {
                    "session_id": gs.session_id,
                    "model": model,
                    "tokens_out": usage.tokens_out,
                    "note": "stop_reason max_tokens: the turn was cut off at the output cap",
                },
                Provenance.CLAUDE,
                job_id=gs.job_id,
                session_id=gs.session_id,
                task_id=gs.task_id,
            )
        return record_call(
            self.store,
            self.prices,
            session_id=gs.session_id if gs else None,
            task_id=gs.task_id if gs else None,
            job_id=gs.job_id if gs else job_id,
            purpose=purpose,
            provider=preset.provider,
            backend_preset=preset_name,
            model=model,
            usage=usage,
            provider_cost_usd=provider_cost,
            status=200,
            latency_ms=int((time.monotonic() - started) * 1000),
            provenance=Provenance.LOCAL if preset.locality == "local" else Provenance.CLAUDE,
            truncated=truncated,
            repo=gs.repo if gs else repo,
            call_key=call_key,
            hold_usd=hold.amount if hold is not None else None,
            hold_reason=(hold.reason or None) if hold is not None else None,
        )

    async def forward(
        self, gs: GatewaySession, path: str, headers: dict[str, str], raw: bytes
    ) -> tuple[int, dict[str, str], AsyncIterator[bytes] | bytes]:
        # The thread places the hold (and the miss premium). If this request is cancelled
        # while it runs, the result must still be released: the thread is shielded and a
        # done-callback gives back whatever it placed.
        pre = asyncio.ensure_future(asyncio.to_thread(self.preflight, gs, path, raw, headers))
        try:
            hold = await asyncio.shield(pre)
        except asyncio.CancelledError:
            pre.add_done_callback(self._release_late)
            raise
        preset, body, raw = hold.preset, hold.body, hold.raw
        try:
            key = self._key(preset)
            req = self.async_client.build_request(
                "POST",
                self._upstream_url(preset, path),
                headers=self._headers(headers, key, preset),
                content=raw,
            )
            started = time.monotonic()
            resp = await self.async_client.send(req, stream=True)
        except httpx2.TransportError as e:  # a timeout or a dropped connection
            self.release(hold)
            self._upstream(gs.preset, False, type(e).__name__, gs.session_id)
            self._upstream_error(gs, {"transport": type(e).__name__})
            raise
        except BaseException:
            self.release(hold)
            self._release_probe(hold.probe)  # the call never reached upstream
            raise
        ctype = resp.headers.get("content-type", "")
        if resp.status_code >= 500 and "text/event-stream" not in ctype:
            # a 500 that says the prompt outgrew its slot's context is the session's
            # own cause, not the backend's health: it neither counts toward the breaker
            # nor ends a run of failures (owner, 2026-10-31)
            try:
                own = bool(self._http_failure(resp.status_code, await resp.aread())["context"])
            except Exception:
                own = False
            except BaseException:  # cancelled mid-read
                await self._abandon(hold, resp)
                raise
            if (
                own
                and self.cfg.preset(gs.preset).locality == "local"
                and (self._exempt_streak(gs.preset, gs.session_id) <= EXEMPT_OVERFLOWS)
            ):
                self._release_probe(hold.probe)
            elif own and self.cfg.preset(gs.preset).locality == "local":
                # a server that only ever answers with overflow is unhealthy
                self._release_probe(hold.probe)
                self._trip_overflow(gs.preset, gs.session_id)
            else:
                self._exempt.pop(gs.preset, None)
                self._upstream(gs.preset, False, f"HTTP {resp.status_code}", gs.session_id)
        else:
            self._exempt.pop(gs.preset, None)  # any other answer ends the overflow run
            self._upstream(
                gs.preset, resp.status_code < 500, f"HTTP {resp.status_code}", gs.session_id
            )
        out_headers = {"content-type": ctype} if ctype else {}
        if path in FREE_PATHS:
            try:
                data = await resp.aread()
            except BaseException:  # cancelled (or failed) mid-read
                await self._abandon(hold, resp)
                raise
            await resp.aclose()
            self.release(hold)
            return resp.status_code, out_headers, data
        if "text/event-stream" in ctype and resp.status_code == 200:
            tap = SSEUsageTap()

            finished = False

            async def finish() -> None:
                """Book the call, then let go of its hold (review round 2, N7). Once: the
                generator's `finally`, `HeldStream.aclose` and the response's background task
                all call it, whichever comes first, so a stream the client leaves before the
                first chunk still releases its hold and premium."""
                nonlocal finished
                if finished:
                    return
                finished = True
                try:
                    await resp.aclose()
                    self._record_or_fail_closed(
                        hold,
                        gs,
                        preset_name=gs.preset,
                        preset=preset,
                        model=tap.model or body["model"],
                        usage=tap.usage(),
                        started=started,
                        purpose="session",
                        stop_reason=tap.stop_reason,
                    )
                finally:
                    self.release(hold)

            async def gen() -> AsyncIterator[bytes]:
                try:
                    async for (
                        chunk
                    ) in resp.aiter_bytes():  # decoded: no content-encoding is passed on
                        tap.feed(chunk)
                        self._touch(gs.session_id)
                        yield chunk
                finally:
                    await finish()

            return resp.status_code, out_headers, HeldStream(gen(), finish)
        try:
            data = await resp.aread()
            await resp.aclose()
            if resp.status_code != 200:
                try:
                    failure = self._http_failure(resp.status_code, data)
                except Exception:  # the summary never changes the status
                    failure = {"status": resp.status_code, "context": False, "model": False}
                self._upstream_error(gs, failure)
            if resp.status_code == 200:
                try:
                    payload = json.loads(data)
                    usage = payload.get("usage") or {}
                    self._record_or_fail_closed(
                        hold,
                        gs,
                        preset_name=gs.preset,
                        preset=preset,
                        model=payload.get("model") or body["model"],
                        usage=usage_from_anthropic(usage),
                        started=started,
                        purpose="session",
                        provider_cost=usage.get("cost"),
                        stop_reason=payload.get("stop_reason"),
                    )
                except json.JSONDecodeError, AttributeError:
                    pass
        finally:
            self.release(hold)  # only after the call is booked (review round 2, N7)
        return resp.status_code, out_headers, data

    # --- vigild's own calls -------------------------------------------------------------

    def metered(
        self,
        *,
        repo: str,
        route: str,
        provider: str,
        model: str,
        purpose: str,
        job_id: str | None,
        run: Callable[[], dict[str, Any]],
        private: bool | None = None,
        body_chars: int = 0,
    ) -> dict[str, Any]:
        """A non-Anthropic call vigild makes itself (Jev): the same route check,
        reservation and per-call row as everything through the gateway (item 11).
        The route is checked against the repo's visibility right before the
        call: the decision's own read when it passes one (one lookup per
        decision, review A10), else a fresh one. A repo read as private never
        reaches OpenRouter (owner, 2026-10-23)."""
        if private is None:
            private = live_private(repo)
        try:
            check_decider_route(self.cfg, repo, route, private=private)
        except RepoPolicyError as e:
            raise GatewayError(403, "permission_error", str(e)) from e
        # the call's worst case, as the other gateway paths reserve it: its
        # input at the dearest input rate, twice over, never under the floor
        # (2a round 8: $0.01 flat let a bigger call settle past its row)
        worst = 2 * self.prices.cost(
            model, CallUsage(tokens_cache_write_1h=math.ceil(body_chars / CHARS_PER_TOKEN),
                             tokens_in=math.ceil(body_chars / CHARS_PER_TOKEN), tokens_out=1024)
        ) if self.prices.has(model) else 0.0  # fmt: skip
        amount = max(self.cfg.budgets.decider_call_usd, worst)
        call_key = uuid.uuid4().hex
        with self._own_call(amount, purpose, job_id) as cost:
            started = time.monotonic()
            payload = run()
            result = payload.get("result", payload) if isinstance(payload, dict) else {}
            usage = (
                (result.get("usage") if isinstance(result, dict) else None)
                or payload.get("usage")
                or {}
            )
            cost[0] = self._own_record(
                amount,
                purpose,
                job_id,
                lambda: record_call(
                    self.store,
                    self.prices,
                    session_id=None,
                    task_id=None,
                    job_id=job_id,
                    purpose=purpose,
                    provider=provider,
                    backend_preset=route,
                    model=model,
                    usage=CallUsage(
                        tokens_in=int(usage.get("input_tokens") or 0),
                        tokens_out=int(usage.get("output_tokens") or 0),
                    ),
                    provider_cost_usd=usage.get("cost"),
                    latency_ms=int((time.monotonic() - started) * 1000),
                    provenance=Provenance.CLAUDE,
                    repo=repo,
                    call_key=call_key,
                ),
                call_key,
            )
            return payload

    def _own_record(
        self,
        amount: float,
        purpose: str,
        job_id: str | None,
        record: Callable[[], float],
        call_key: str,
    ) -> float:
        """Record one of vigild's own calls and return its cost, exactly once by
        `call_key` (#29). If recording fails, look the row up by key: found, its
        cost is booked once; not found, the cost is unknown (#16's rule): book the
        call's reservation (`amount`, never more). Either way, page."""
        try:
            return record()
        except Exception as e:
            reason = redact(f"{type(e).__name__}: {e}")
            written: float | None = None
            try:
                written = call_cost_by_key(self.store, call_key)
            except Exception:
                log.exception("call_key lookup failed for %s", call_key)
            booked = amount if written is None else written
            log.error("metering failed for vigild's own %s call: %s", purpose, reason)
            try:
                self.store.add_event(
                    "metering_failed",
                    {"purpose": purpose, "error": reason, "booked_usd": booked,
                     "call_key": call_key, "row_written": written is not None},
                    Provenance.HUMAN, job_id=job_id,
                )  # fmt: skip
                self.store.create_inbox_item(
                    "questions", "page", job_id,
                    f"metering failed after the record was written: {reason}; {purpose} "
                    f"call booked at its recorded cost" if written is not None else
                    f"metering failed: {reason}; {purpose} call booked at its reservation",
                    {"purpose": purpose, "booked_usd": booked, "call_key": call_key,
                     "row_written": written is not None,
                     "note": f"The call's row was written; its recorded cost (${booked:.4f}) "
                     "was booked once." if written is not None else
                     f"Metering failed for this call; its cost was booked at its "
                     f"reservation (${amount:.4f}). No row carries its key: not counted twice.",
                     "resumable": False},
                )  # fmt: skip
            except Exception:
                log.exception("metering-failure page failed")
            return booked

    @contextmanager
    def _own_call(
        self, amount: float, purpose: str, job_id: str | None = None
    ) -> Iterator[list[float]]:
        """One of vigild's own calls (Jev through `metered`, Haiku through
        `call`): reserve its worst case, keep that reservation live while the
        call is in flight (2a round 9), then settle it at the call's cost,
        never past what was reserved. A cost past it is recorded
        (`settle_excess`) and trips the daily breaker (2a rounds 8-9), on
        both paths. The caller sets the yielded list's one item to the cost. `job_id`
        is the job the call is for: a bench job's own calls draw from the experiment
        line, never the day (owner's rule)."""
        try:
            rid = self.budget.reserve(
                session_id=None, task_id=None, amount=amount, purpose=purpose, job_id=job_id
            )
        except BudgetExceeded as e:
            raise GatewayError(403, "permission_error", str(e)) from e
        with self._inflight_lock:
            self._own[rid] = self._now()
        cost = [0.0]
        try:
            yield cost
        finally:
            try:
                self.budget.settle(rid, cost[0])  # first: the sweep never sees it unheld
            finally:
                with self._inflight_lock:
                    self._own.pop(rid, None)
            if cost[0] > amount + 1e-9 and self.breakers is not None:
                from vigild.breakers import GLOBAL, Kind

                self.breakers.trip(
                    Kind.DAILY, GLOBAL,
                    {"why": "a call vigild made cost more than its reservation",
                     "reserved_usd": round(amount, 6), "cost_usd": round(cost[0], 6)},
                )  # fmt: skip

    def _fallback_today(self, repo: str) -> float:
        day = utcnow().strftime("%Y-%m-%d")
        rows = self.store.q(
            "SELECT COALESCE(SUM(cost_usd), 0) n FROM model_calls"
            " WHERE purpose=? AND repo=? AND ts LIKE ?",
            (FALLBACK_PURPOSE, repo, f"{day}%"),
        )
        return float(rows[0]["n"])

    def _fallback_hold(self, repo: str, amount: float) -> None:
        """Owner ruling 4: a repo's Haiku fallback spend has its own daily cap.
        A call that would cross it is refused before it is sent; the repo's
        fallback breaker trips, pages, and holds the repo's dispatch."""
        from vigild.breakers import Kind

        scope = f"repo:{repo}"
        cap = self.cfg.budgets.decider_fallback_per_repo_usd
        with self._inflight_lock:
            open_ = self.breakers is not None and self.breakers.is_open(
                Kind.DECIDER_FALLBACK, scope
            )
            spent = self._fallback_today(repo) + self._fallback_pending.get(repo, 0.0)
            if open_ or spent + amount > cap:
                if self.breakers is not None:
                    self.breakers.trip(
                        Kind.DECIDER_FALLBACK, scope,
                        {"spent_today_usd": round(spent, 6), "cap_usd": cap,
                         "next": "Jev has drifted or is failing: check the Jev pages, then reset"},
                    )  # fmt: skip
                raise GatewayError(
                    403, "permission_error",
                    f"decider fallback cap: {repo} has ${spent:.4f} of ${cap:.2f} today",
                )  # fmt: skip
            self._fallback_pending[repo] = self._fallback_pending.get(repo, 0.0) + amount

    def _fallback_done(self, repo: str, amount: float) -> None:
        with self._inflight_lock:
            self._fallback_pending[repo] = max(0.0, self._fallback_pending.get(repo, 0.0) - amount)

    def call(
        self,
        *,
        repo: str,
        preset: str,
        body: dict[str, Any],
        purpose: str,
        job_id: str | None,
        private: bool | None = None,
    ) -> dict[str, Any]:
        """vigild's own Anthropic call (the Haiku decider). `private` is the
        decision's visibility read (review A10); without it, read now."""
        if private is None:
            private = live_private(repo)
        p = self._preset(repo, preset, private=private)
        body = {**body, "model": p.model}
        raw = json.dumps(body).encode()
        model = self._check_model(repo, p, p.model)
        worst = self.worst_case(model, body, len(raw))
        amount = max(worst, self.cfg.budgets.decider_call_usd)
        fallback = purpose == FALLBACK_PURPOSE
        if fallback:
            self._fallback_hold(repo, amount)
        try:
            probe = self._backend_gate(preset)
            try:
                return self._call(repo, preset, p, model, raw, amount, purpose, job_id)
            except GatewayError:
                self._release_probe(probe)  # refused before upstream (the budget)
                raise
        finally:
            if fallback:
                self._fallback_done(repo, amount)

    def _call(
        self,
        repo: str,
        preset: str,
        p: Preset,
        model: str,
        raw: bytes,
        amount: float,
        purpose: str,
        job_id: str | None,
    ) -> dict[str, Any]:
        call_key = uuid.uuid4().hex
        with self._own_call(amount, purpose, job_id) as cost:
            started = time.monotonic()
            try:
                resp = self.sync_client.post(
                    self._upstream_url(p, "/v1/messages"),
                    headers=self._headers({}, self._key(p), p),
                    content=raw,
                )
            except httpx2.TransportError as e:
                self._upstream(preset, False, type(e).__name__)
                raise
            self._upstream(preset, resp.status_code < 500, f"HTTP {resp.status_code}")
            payload: dict[str, Any] = resp.json()
            if resp.status_code != 200:
                raise GatewayError(
                    resp.status_code,
                    "api_error",
                    f"upstream {resp.status_code}: {payload.get('error')}",
                )
            cost[0] = self._own_record(
                amount,
                purpose,
                job_id,
                lambda: self._record(
                    gs=None,
                    preset_name=preset,
                    preset=p,
                    model=payload.get("model") or model,
                    usage=usage_from_anthropic(payload.get("usage") or {}),
                    started=started,
                    purpose=purpose,
                    job_id=job_id,
                    repo=repo,
                    call_key=call_key,
                ),
                call_key,
            )
            return payload

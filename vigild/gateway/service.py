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

import hashlib
import json
import math
import secrets
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx2

from vigild.budget import Budget, BudgetExceeded
from vigild.config import Config, Preset, Secrets
from vigild.db import Store, iso
from vigild.metering.calls import CallUsage, SSEUsageTap, record_call, usage_from_anthropic
from vigild.metering.prices import PriceTable
from vigild.provenance import Provenance
from vigild.repos import RepoPolicyError, check_backend

FORWARD_HEADERS = ("anthropic-version", "anthropic-beta", "content-type", "accept")
METERED_PATHS = ("/v1/messages",)
FREE_PATHS = ("/v1/messages/count_tokens",)
CHARS_PER_TOKEN = 3  # deliberately low, so the input estimate errs high
DEFAULT_MAX_TOKENS = 4096
UPSTREAM_TIMEOUT = httpx2.Timeout(600.0, connect=10.0)


class GatewayError(Exception):
    def __init__(self, status: int, kind: str, message: str) -> None:
        super().__init__(message)
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
        self.prices = PriceTable(cfg.prices)
        self.sync_client = httpx2.Client(transport=transport, timeout=UPSTREAM_TIMEOUT)
        self.async_client = httpx2.AsyncClient(transport=async_transport, timeout=UPSTREAM_TIMEOUT)

    # --- tokens -------------------------------------------------------------------

    def issue_token(self, session_id: str, repo: str, preset: str) -> str:
        check_backend(self.cfg, repo, preset)
        token = "vgw_" + secrets.token_urlsafe(32)
        self.store.x(
            "INSERT INTO gateway_tokens (token_hash, session_id, repo, backend_preset, created_at)"
            " VALUES (?,?,?,?,?)",
            (_hash(token), session_id, repo, preset, iso()),
        )
        return token

    def revoke(self, session_id: str) -> None:
        self.store.x(
            "UPDATE gateway_tokens SET revoked_at=? WHERE session_id=? AND revoked_at IS NULL",
            (iso(), session_id),
        )

    def authorize(self, token: str | None) -> GatewaySession:
        if not token:
            raise GatewayError(401, "authentication_error", "missing session token")
        rows = self.store.q(
            "SELECT g.session_id, g.repo, g.backend_preset, g.revoked_at, s.task_id, s.job_id"
            " FROM gateway_tokens g LEFT JOIN sessions s ON s.id = g.session_id"
            " WHERE g.token_hash=?",
            (_hash(token),),
        )
        if not rows or rows[0]["revoked_at"]:
            raise GatewayError(401, "authentication_error", "invalid or revoked session token")
        r = rows[0]
        return GatewaySession(
            r["session_id"], r["repo"], r["backend_preset"], r["task_id"], r["job_id"]
        )

    # --- checks ---------------------------------------------------------------------

    def _preset(self, repo: str, preset_name: str) -> Preset:
        try:
            check_backend(self.cfg, repo, preset_name)
        except RepoPolicyError as e:
            raise GatewayError(403, "permission_error", str(e)) from e
        preset = self.cfg.preset(preset_name)
        if preset.kind.value != "anthropic":
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

    def _check_model(self, repo: str, preset: Preset, model: str | None) -> str:
        if not model:
            raise GatewayError(400, "invalid_request_error", "model is required")
        if model not in self._allowed_models(repo, preset.provider):
            raise GatewayError(
                403,
                "permission_error",
                f"model {model} is not one {repo} may use (configs/repos.yaml)",
            )
        if not self.prices.has(model):
            raise GatewayError(403, "permission_error", f"model {model} has no price; refused")
        return model

    def worst_case(self, model: str, body: dict[str, Any], raw_len: int) -> float:
        est_in = math.ceil(raw_len / CHARS_PER_TOKEN)
        max_out = int(body.get("max_tokens") or DEFAULT_MAX_TOKENS)
        return self.prices.cost(model, CallUsage(tokens_in=est_in, tokens_out=max_out))

    def _key(self, preset: Preset) -> str:
        key = self.secrets.get(preset.key_ref)
        if not key:
            raise GatewayError(503, "api_error", f"{preset.key_ref} is not set in the env file")
        return key

    def _refuse(self, gs: GatewaySession, err: GatewayError) -> GatewayError:
        self.store.add_event(
            "gateway_refused",
            {"status": err.status, "reason": err.message},
            Provenance.HUMAN,
            job_id=gs.job_id,
            session_id=gs.session_id,
            task_id=gs.task_id,
        )
        return err

    def preflight(self, gs: GatewaySession, path: str, raw: bytes) -> tuple[Preset, dict[str, Any]]:
        if path not in METERED_PATHS + FREE_PATHS:
            raise GatewayError(404, "not_found_error", f"{path} is not served")
        try:
            preset = self._preset(gs.repo, gs.preset)
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError as e:
                raise GatewayError(400, "invalid_request_error", "body is not JSON") from e
            model = self._check_model(gs.repo, preset, body.get("model"))
            if path in METERED_PATHS:
                worst = self.worst_case(model, body, len(raw))
                headroom = self.budget.session_headroom(gs.session_id)
                if worst > headroom:
                    raise GatewayError(
                        403,
                        "permission_error",
                        f"budget: this call could cost ${worst:.4f}; the session has "
                        f"${headroom:.4f} of its reservation left",
                    )
        except GatewayError as e:
            raise self._refuse(gs, e) from None
        return preset, body

    # --- forwarding ------------------------------------------------------------------

    def _headers(self, incoming: dict[str, str], key: str) -> dict[str, str]:
        out = {h: incoming[h] for h in FORWARD_HEADERS if h in incoming}
        out.setdefault("anthropic-version", "2023-06-01")
        out.setdefault("content-type", "application/json")
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
    ) -> float:
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
        )

    async def forward(
        self, gs: GatewaySession, path: str, headers: dict[str, str], raw: bytes
    ) -> tuple[int, dict[str, str], AsyncIterator[bytes] | bytes]:
        preset, body = self.preflight(gs, path, raw)
        key = self._key(preset)
        url = preset.base_url.rstrip("/") + path
        req = self.async_client.build_request(
            "POST", url, headers=self._headers(headers, key), content=raw
        )
        started = time.monotonic()
        resp = await self.async_client.send(req, stream=True)
        ctype = resp.headers.get("content-type", "")
        out_headers = {"content-type": ctype} if ctype else {}
        if path in FREE_PATHS:
            data = await resp.aread()
            await resp.aclose()
            return resp.status_code, out_headers, data
        if "text/event-stream" in ctype and resp.status_code == 200:
            tap = SSEUsageTap()

            async def gen() -> AsyncIterator[bytes]:
                try:
                    async for (
                        chunk
                    ) in resp.aiter_bytes():  # decoded: no content-encoding is passed on
                        tap.feed(chunk)
                        yield chunk
                finally:
                    await resp.aclose()
                    self._record(
                        gs=gs,
                        preset_name=gs.preset,
                        preset=preset,
                        model=tap.model or body["model"],
                        usage=tap.usage(),
                        started=started,
                        purpose="session",
                    )

            return resp.status_code, out_headers, gen()
        data = await resp.aread()
        await resp.aclose()
        if resp.status_code == 200:
            try:
                payload = json.loads(data)
                usage = payload.get("usage") or {}
                self._record(
                    gs=gs,
                    preset_name=gs.preset,
                    preset=preset,
                    model=payload.get("model") or body["model"],
                    usage=usage_from_anthropic(usage),
                    started=started,
                    purpose="session",
                    provider_cost=usage.get("cost"),
                )
            except json.JSONDecodeError, AttributeError:
                pass
        return resp.status_code, out_headers, data

    # --- vigild's own calls -------------------------------------------------------------

    def call(
        self, *, repo: str, preset: str, body: dict[str, Any], purpose: str, job_id: str | None
    ) -> dict[str, Any]:
        p = self._preset(repo, preset)
        body = {**body, "model": p.model}
        raw = json.dumps(body).encode()
        model = self._check_model(repo, p, p.model)
        worst = self.worst_case(model, body, len(raw))
        amount = max(worst, self.cfg.budgets.decider_call_usd)
        try:
            rid = self.budget.reserve(session_id=None, task_id=None, amount=amount, purpose=purpose)
        except BudgetExceeded as e:
            raise GatewayError(403, "permission_error", str(e)) from e
        started = time.monotonic()
        try:
            resp = self.sync_client.post(
                p.base_url.rstrip("/") + "/v1/messages",
                headers=self._headers({}, self._key(p)),
                content=raw,
            )
            payload: dict[str, Any] = resp.json()
            if resp.status_code != 200:
                raise GatewayError(
                    resp.status_code,
                    "api_error",
                    f"upstream {resp.status_code}: {payload.get('error')}",
                )
            cost = self._record(
                gs=None,
                preset_name=preset,
                preset=p,
                model=payload.get("model") or model,
                usage=usage_from_anthropic(payload.get("usage") or {}),
                started=started,
                purpose=purpose,
                job_id=job_id,
            )
            self.budget.settle(rid, cost)
            return payload
        except BaseException:
            self.budget.settle(rid, 0.0)
            raise

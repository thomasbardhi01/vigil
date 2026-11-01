"""The gateway's HTTP face: a separate listener from the REST API, so API
tokens never work here and session tokens never work there. Workers reach
it at http://host.docker.internal:8788 through their egress proxy, with
ANTHROPIC_BASE_URL pointing here and the session token as the auth token."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from vigild.gateway.service import Gateway, GatewayError


def _token(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key:
        return key
    auth = request.headers.get("authorization", "")
    return auth[7:].strip() if auth.lower().startswith("bearer ") else None


class _HeldResponse(StreamingResponse):
    """A streamed answer whose call is booked and hold released (`finish`, idempotent)
    however the ASGI exchange ends: sent, cut off, or a `send` that fails before the
    response starts (where a server may skip the background task)."""

    def __init__(self, stream: AsyncIterator[bytes], finish: Any, **kw: Any) -> None:
        super().__init__(stream, **kw)
        self._finish = finish

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self._finish()


def create_gateway_app(gw: Gateway) -> FastAPI:
    app = FastAPI(title="vigil gateway", docs_url=None, redoc_url=None, openapi_url=None)

    async def _proxy(request: Request, path: str) -> Response:
        try:
            gs = gw.authorize(_token(request))
            raw = await request.body()
            headers = {k.lower(): v for k, v in request.headers.items()}
            status, out_headers, body = await gw.forward(gs, path, headers, raw)
        except GatewayError as e:
            return JSONResponse(e.body(), status_code=e.status)
        if isinstance(body, bytes):
            return Response(body, status_code=status, headers=out_headers)
        stream: AsyncIterator[bytes] = body
        # A client that leaves before the first chunk never starts the generator, so its
        # `finally` never runs: the response's background task books the call and releases
        # the hold (idempotent with the generator's own).
        finish = getattr(body, "finish", None)
        if finish is None:
            return StreamingResponse(stream, status_code=status, headers=out_headers)
        return _HeldResponse(
            stream,
            finish,
            status_code=status,
            headers=out_headers,
            background=BackgroundTask(finish),
        )

    @app.get("/health")
    async def health() -> dict[str, bool]:
        # no token, no state: a sandbox host's doctor probe reaches it through
        # the egress proxy to prove the path to the gateway (ADR-0004)
        return {"ok": True}

    @app.post("/v1/messages")
    async def messages(request: Request) -> Response:
        return await _proxy(request, "/v1/messages")

    @app.post("/v1/messages/count_tokens")
    async def count_tokens(request: Request) -> Response:
        return await _proxy(request, "/v1/messages/count_tokens")

    return app

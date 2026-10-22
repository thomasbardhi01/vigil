"""Bearer-token auth with three scopes (B7): admin, read, heartbeat.

admin can do everything; read can GET; heartbeat can only post heartbeats
(phase 3). A scope whose token is unset matches nothing.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from enum import StrEnum

from fastapi import HTTPException, Request

from vigild.services import Services, Tokens


class Scope(StrEnum):
    ADMIN = "admin"
    READ = "read"
    HEARTBEAT = "heartbeat"


GRANTS: dict[Scope, set[Scope]] = {
    Scope.ADMIN: {Scope.ADMIN, Scope.READ, Scope.HEARTBEAT},
    Scope.READ: {Scope.READ},
    Scope.HEARTBEAT: {Scope.HEARTBEAT},
}


def identify(tokens: Tokens, header: str | None) -> Scope | None:
    if not header or not header.startswith("Bearer "):
        return None
    presented = header[len("Bearer ") :].strip().encode()
    if not presented:
        return None
    found: Scope | None = None
    for scope, token in (
        (Scope.ADMIN, tokens.admin),
        (Scope.READ, tokens.read),
        (Scope.HEARTBEAT, tokens.heartbeat),
    ):
        if token and hmac.compare_digest(presented, token.encode()) and found is None:
            found = scope
    return found


def require(needed: Scope) -> Callable[[Request], Scope]:
    def dep(request: Request) -> Scope:
        services: Services = request.app.state.services
        scope = identify(services.tokens, request.headers.get("authorization"))
        if scope is None:
            raise HTTPException(401, "missing or invalid bearer token")
        if needed not in GRANTS[scope]:
            raise HTTPException(403, f"the {scope.value} token can't do this")
        return scope

    return dep

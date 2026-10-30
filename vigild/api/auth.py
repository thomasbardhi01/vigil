"""Auth (decision `api-auth`): bearer tokens with three scopes, plus the web UI's session cookie.

admin can do everything; read can GET; heartbeat can only post heartbeats
(phase 3). A scope whose token is unset matches nothing.

coord (issue #146) is the coord's own token: what admin can do, except that vigild
derives the actor from the token (`actor_of`, never from a body), an approval must cite a
ruling, and a route that edits a budget or cap, moves a rung or merges is refused outright
(`COORD_REFUSED`), as is approving a spec that touches `ladder_pinned_paths` (the approve
routes check it). The web UI's login takes the admin or read token only.

The web UI never stores a token (P7: no). `POST /api/login` takes the admin
or read token once and sets `vigil_session`: a random id (stored hashed),
HttpOnly, SameSite=Strict, Path=/, 12 hours, Secure when the UI is served over
HTTPS. A write made with the cookie must also carry `X-Vigil-UI: 1`, which a
cross-site form can't send. The CLI and MCP keep bearer tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import datetime, timedelta
from enum import StrEnum

from fastapi import HTTPException, Request

from vigild.db import Store, iso, utcnow
from vigild.services import Services, Tokens

COOKIE = "vigil_session"
UI_SESSION_TTL = timedelta(hours=12)
UI_HEADER = "x-vigil-ui"
SAFE = {"GET", "HEAD", "OPTIONS"}
# A write whose route has one of these path words is the owner's alone. No route edits a
# cap or a rung or merges today (policy is configs/*.yaml by PR; merging is on GitHub); a
# route added later at such a place is refused for the coord token before its handler runs.
COORD_REFUSED = frozenset({"budget", "budgets", "cap", "caps", "rung", "rungs", "ladder", "merge"})


class Scope(StrEnum):
    ADMIN = "admin"
    READ = "read"
    HEARTBEAT = "heartbeat"
    COORD = "coord"


GRANTS: dict[Scope, set[Scope]] = {
    Scope.ADMIN: {Scope.ADMIN, Scope.READ, Scope.HEARTBEAT},
    Scope.READ: {Scope.READ},
    Scope.HEARTBEAT: {Scope.HEARTBEAT},
    Scope.COORD: {Scope.ADMIN, Scope.READ, Scope.HEARTBEAT, Scope.COORD},
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
        (Scope.COORD, tokens.coord),
    ):
        if token and hmac.compare_digest(presented, token.encode()) and found is None:
            found = scope
    return found


def _h(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_ui_session(store: Store, scope: Scope) -> str:
    raw = secrets.token_urlsafe(32)
    now = utcnow()
    store.x(
        "INSERT INTO ui_sessions (id_hash, scope, created_at, expires_at) VALUES (?,?,?,?)",
        (_h(raw), scope.value, iso(now), iso(now + UI_SESSION_TTL)),
    )
    return raw


def ui_session_scope(store: Store, raw: str | None) -> Scope | None:
    if not raw:
        return None
    rows = store.q(
        "SELECT scope, expires_at, revoked_at FROM ui_sessions WHERE id_hash=?", (_h(raw),)
    )
    if not rows or rows[0]["revoked_at"]:
        return None
    if datetime.fromisoformat(rows[0]["expires_at"]) <= utcnow():
        return None
    return Scope(rows[0]["scope"])


def end_ui_session(store: Store, raw: str | None) -> None:
    if raw:
        store.x("UPDATE ui_sessions SET revoked_at=? WHERE id_hash=?", (iso(), _h(raw)))


def require(needed: Scope) -> Callable[[Request], Scope]:
    def dep(request: Request) -> Scope:
        services: Services = request.app.state.services
        scope = identify(services.tokens, request.headers.get("authorization"))
        ui = bool(getattr(request.app.state, "ui", False))
        if ui and scope is None and "authorization" not in request.headers:
            scope = ui_session_scope(services.store, request.cookies.get(COOKIE))
            unsafe = scope is not None and request.method not in SAFE
            if unsafe and request.headers.get(UI_HEADER) != "1":
                raise HTTPException(403, "a write from the UI needs the X-Vigil-UI header")
        if scope is None:
            raise HTTPException(401, "missing or invalid bearer token")
        if needed not in GRANTS[scope]:
            raise HTTPException(403, f"the {scope.value} token can't do this")
        if scope is Scope.COORD and request.method not in SAFE:
            route = request.scope.get("route")
            path = str(getattr(route, "path", None) or request.url.path)
            if COORD_REFUSED & set(path.lower().strip("/").split("/")):
                raise HTTPException(403, "the coord token can't do this; it is the owner's")
        request.state.scope = scope
        request.state.authed = True  # the channel middleware logs only authenticated calls
        return scope

    return dep


def actor_of(request: Request) -> tuple[str, str]:
    """(actor, channel) for a state change, from the token that authenticated the call. The
    coord token is `coord` over `mcp`; every other is the owner, from the inbox."""
    if getattr(request.state, "scope", None) is Scope.COORD:
        return "coord", "mcp"
    return "owner", "inbox"

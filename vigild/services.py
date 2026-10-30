"""What the API and the runner share: config, store, tokens, the job service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vigild.config import Config
    from vigild.db import Store
    from vigild.jobs.service import JobService


@dataclass
class Tokens:
    """Decision `api-auth`'s bearer scopes, plus the coord's own token (#146). None means
    the scope is off; nothing matches it."""

    admin: str | None
    read: str | None
    heartbeat: str | None
    coord: str | None = None


@dataclass
class Services:
    cfg: Config
    store: Store
    tokens: Tokens
    jobs: JobService
    # Features switched off because a credential is missing, e.g. "github-app".
    degraded: set[str] = field(default_factory=set)
    # docs/owner-rulings.md as it is on main (vigild's mirror, `rulings.from_mirror`); None,
    # or a source that returns None, refuses every coord ruling (#146, owner 2026-10-30)
    rulings_source: Callable[[], str | None] | None = None

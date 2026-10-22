"""Policy as code: configs/*.yaml, validated at load. Plus the env file.

vigild refuses to start on an invalid config, including a private repo that
lists a hosted backend or decider route it may not use (vigild/repos.py).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from vigild.contract.models import Backend

CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"
DEFAULT_ENV_FILE = Path("~/.config/vigil/env").expanduser()


class ConfigError(ValueError):
    pass


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Preset(Backend):
    locality: Literal["hosted", "local"]
    provider: str
    live: bool = True


class DeciderRoute(_M):
    backend: Literal["haiku", "jev_cloudflare", "jev_openrouter", "lfm_tower"]
    provider: str
    locality: Literal["hosted", "local"]
    preset: str | None = None
    model: str | None = None
    key_ref: str | None = None
    live: bool = True


class BackendsFile(_M):
    presets: dict[str, Preset]
    decider_routes: dict[str, DeciderRoute]


class RepoPolicy(_M):
    visibility: Literal["public", "private"]
    decider: list[str]
    backends: list[str]
    worker_overflow: list[str] = Field(default_factory=list)
    auto_merge: bool = False
    dev_image: str  # the pinned image this repo's sessions run in
    dev_image_check: str  # smoke command the validation runs in it
    # Commands a test_cmd may use in this image; validated present. A test_cmd
    # that needs anything else is refused at the spec gate (review r1, blocker 4).
    dev_image_tools: list[str]


class ReposFile(_M):
    repos: dict[str, RepoPolicy]


class Routing(_M):
    tiers: dict[str, str]
    fallback: str
    coord: str
    reviewer: str
    auditor: str
    money_paths: list[str]
    architecture_labels: list[str]
    architecture_paths: list[str]
    local_labels: list[str]
    xs_labels: list[str]
    escalate_attempt: int = 3
    escalate_review_rounds: int = 2


class Budgets(_M):
    daily_usd: float = Field(gt=0)
    per_task_usd: float = Field(gt=0)
    monthly_usd: float = Field(gt=0)  # mandatory: no default
    wip_per_repo: int = Field(ge=1)
    coord_session_usd: float = Field(gt=0)
    decider_call_usd: float = Field(gt=0)


class LongContext(_M):
    threshold: int
    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float


class ModelPrice(_M):
    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float
    long_context: LongContext | None = None


class Prices(_M):
    as_of: str
    models: dict[str, ModelPrice]


class GatewayEgress(_M):
    host: str
    port: int
    allow_address: str


class ProxyEgress(_M):
    alias: str
    port: int


class CollectorEgress(_M):
    host: str
    port: int


class Egress(_M):
    gateway: GatewayEgress
    collector: CollectorEgress
    proxy: ProxyEgress
    roles: dict[str, list[str]]


class Bind(_M):
    host: str
    port: int
    tailscale_host: str | None = None
    # The UI session cookie's Secure flag: true only when the UI is reached over
    # HTTPS (`tailscale serve`); a Secure cookie is never sent over plain HTTP.
    cookie_secure: bool = False


class Images(_M):
    claude_executor: str
    egress_proxy: str


class Collector(_M):
    container: str
    otlp_http: str


class GitHub(_M):
    owner: str
    claude_mods: str
    claude_mods_sha: str


class ContainerLimits(_M):
    memory: str
    pids_limit: int
    uid: int


class Vigild(_M):
    data_dir: str
    api: Bind
    gateway: Bind
    fleet_coord: str
    images: Images
    collector: Collector
    github: GitHub
    container: ContainerLimits

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).expanduser()


class Config(_M):
    backends: BackendsFile
    repos: ReposFile
    routing: Routing
    budgets: Budgets
    prices: Prices
    egress: Egress
    vigild: Vigild

    def preset(self, name: str) -> Preset:
        try:
            return self.backends.presets[name]
        except KeyError as e:
            raise ConfigError(f"unknown backend preset {name!r}") from e

    def repo(self, name: str) -> RepoPolicy:
        try:
            return self.repos.repos[name]
        except KeyError as e:
            raise ConfigError(f"repo {name!r} is not in configs/repos.yaml") from e


FILES = {
    "backends": "backends.yaml",
    "repos": "repos.yaml",
    "routing": "routing.yaml",
    "budgets": "budgets.yaml",
    "prices": "prices.yaml",
    "egress": "egress.yaml",
    "vigild": "vigild.yaml",
}


def load(config_dir: Path = CONFIG_DIR, overrides: Mapping[str, object] | None = None) -> Config:
    raw: dict[str, object] = {}
    for key, fname in FILES.items():
        raw[key] = yaml.safe_load((config_dir / fname).read_text())
    raw.update(overrides or {})
    cfg = Config.model_validate(raw)
    validate(cfg)
    return cfg


def validate(cfg: Config) -> None:
    from vigild.repos import validate_repo_policies  # import here: repos imports config's types

    presets = cfg.backends.presets
    for tier, preset in cfg.routing.tiers.items():
        if preset not in presets:
            raise ConfigError(f"routing tier {tier} names unknown preset {preset}")
    for role in ("fallback", "coord", "reviewer", "auditor"):
        if getattr(cfg.routing, role) not in presets:
            raise ConfigError(f"routing.{role} names an unknown preset")
    for name, route in cfg.backends.decider_routes.items():
        if route.preset and route.preset not in presets:
            raise ConfigError(f"decider route {name} names unknown preset {route.preset}")
    for p in presets.values():
        if p.model and p.locality == "hosted" and p.model not in cfg.prices.models:
            raise ConfigError(f"no price for hosted model {p.model} in prices.yaml")
    validate_repo_policies(cfg)


# --- the env file -------------------------------------------------------------


class Secrets:
    """Values from ~/.config/vigil/env. Never printed: repr shows names only."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def get(self, name: str) -> str | None:
        v = self._values.get(name)
        return v if v else None

    def names(self) -> list[str]:
        return sorted(k for k, v in self._values.items() if v)

    def __repr__(self) -> str:
        return f"Secrets(names={self.names()})"


def parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        out[k] = v
    return out


def load_secrets(path: Path = DEFAULT_ENV_FILE) -> Secrets:
    """vigild's startup read of the env file. Refuses a file others can read."""
    if not path.exists():
        return Secrets({})
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise ConfigError(f"{path} must be mode 600 (is {oct(mode)})")
    return Secrets(parse_env(path.read_text()))


def env_override(name: str) -> str | None:
    """Non-secret overrides for tests and CI (e.g. VIGIL_DATA_DIR)."""
    return os.environ.get(name) or None

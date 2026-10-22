"""vigild's startup: load configs and the env file once, build the services,
serve the REST API and the model gateway on two listeners.

  uv run python -m vigild
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn

from vigild import config
from vigild.api.app import create_app
from vigild.budget import Budget
from vigild.config import Config, Secrets
from vigild.db import Store
from vigild.gateway.app import create_gateway_app
from vigild.gateway.service import Gateway
from vigild.jobs.service import JobService, Runner
from vigild.services import Services, Tokens
from vigild.telemetry.spans import Telemetry

log = logging.getLogger("vigild")

# Features and the variables that switch them on (runbook "Credentials").
FEATURES: dict[str, tuple[str, ...]] = {
    "api": ("VIGIL_API_TOKEN",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "github-app": ("GITHUB_APP_ID", "GITHUB_APP_KEY_PATH"),
    "tracing": ("PHOENIX_ADMIN_SECRET",),
    "jev-cloudflare": ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"),
    "metrics-token": ("VIGIL_METRICS_TOKEN",),
}


def degraded(secrets: Secrets) -> set[str]:
    return {f for f, names in FEATURES.items() if not all(secrets.get(n) for n in names)}


class NullRunner:
    def on_job_created(self, job_id: str, needs_spec: bool) -> None:
        log.info("job %s created (needs_spec=%s); no runner attached", job_id, needs_spec)

    def on_approved(self, job_id: str) -> None:
        log.info("job %s approved; no runner attached", job_id)


@dataclass
class Vigild:
    cfg: Config
    secrets: Secrets
    store: Store
    budget: Budget
    gateway: Gateway
    telemetry: Telemetry
    services: Services


def build(
    *,
    config_dir: Path = config.CONFIG_DIR,
    env_file: Path = config.DEFAULT_ENV_FILE,
    data_dir: Path | None = None,
    runner: Runner | None = None,
    **gateway_kwargs: Any,
) -> Vigild:
    cfg = config.load(config_dir)
    if data_dir is not None:
        cfg.vigild.data_dir = str(data_dir)
    secrets = config.load_secrets(env_file)
    data = cfg.vigild.data_path
    data.mkdir(parents=True, exist_ok=True)
    store = Store.open(data / "vigil.db")
    budget = Budget(store, cfg.budgets)
    gateway = Gateway(cfg, store, budget, secrets, **gateway_kwargs)
    off = degraded(secrets)
    telemetry = Telemetry(None if "tracing" in off else cfg.vigild.collector.otlp_http)
    tokens = Tokens(
        admin=secrets.get("VIGIL_API_TOKEN"),
        read=secrets.get("VIGIL_METRICS_TOKEN"),
        heartbeat=secrets.get("VIGIL_HEARTBEAT_TOKEN"),
    )
    jobs = JobService(cfg, store, runner or NullRunner())
    services = Services(cfg=cfg, store=store, tokens=tokens, jobs=jobs, degraded=off)
    for f in sorted(off):
        log.warning("config: %s is off (missing %s)", f, ", ".join(FEATURES[f]))
    return Vigild(cfg, secrets, store, budget, gateway, telemetry, services)


async def serve(v: Vigild) -> None:
    api = v.cfg.vigild.api
    gw = v.cfg.vigild.gateway
    servers = [
        uvicorn.Server(
            uvicorn.Config(create_app(v.services), host=api.host, port=api.port, log_level="info")
        ),
        uvicorn.Server(
            uvicorn.Config(
                create_gateway_app(v.gateway), host=gw.host, port=gw.port, log_level="info"
            )
        ),
    ]
    if api.tailscale_host:
        servers.append(
            uvicorn.Server(
                uvicorn.Config(
                    create_app(v.services), host=api.tailscale_host, port=api.port, log_level="info"
                )
            )
        )
    await asyncio.gather(*(s.serve() for s in servers))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from vigild.jobs.runner import build_runner

    v = build()
    v.services.jobs.runner = build_runner(v)
    asyncio.run(serve(v))

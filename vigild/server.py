"""vigild's startup: load configs and the env file once, build the services,
serve the REST API and the model gateway on two listeners.

  uv run python -m vigild
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import uvicorn

from vigild import config
from vigild.api.app import create_app
from vigild.budget import Budget
from vigild.config import Config, Secrets
from vigild.db import Store
from vigild.devimage import DevImages
from vigild.gateway.app import create_gateway_app
from vigild.gateway.service import Gateway
from vigild.jobs.runner import JobRunner
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

    def on_resume(self, job_id: str) -> None:
        log.info("job %s resumed; no runner attached", job_id)


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
    """Loopback: the bearer-only API and the gateway. The Tailscale address: the
    API with the UI's cookie login (P7). No Tailscale address, no UI login."""
    api = v.cfg.vigild.api
    gw = v.cfg.vigild.gateway
    configs = [
        uvicorn.Config(create_app(v.services), host=api.host, port=api.port, log_level="info"),
        uvicorn.Config(create_gateway_app(v.gateway), host=gw.host, port=gw.port, log_level="info"),
    ]
    if api.tailscale_host:
        configs.append(
            uvicorn.Config(
                create_app(v.services, ui=True),
                host=api.tailscale_host,
                port=api.port,
                log_level="info",
            )
        )
    else:
        log.warning("config: web UI login is off (api.tailscale_host is not set)")
    await asyncio.gather(*(uvicorn.Server(c).serve() for c in configs))


def _github_app(v: Vigild) -> Any:
    import httpx2

    from vigild.github.app import GitHubApp

    app_id, key_path = v.secrets.get("GITHUB_APP_ID"), v.secrets.get("GITHUB_APP_KEY_PATH")
    if not (app_id and key_path):
        return None
    return GitHubApp(
        app_id,
        Path(key_path).expanduser().read_bytes(),
        http=httpx2.Client(timeout=30),
        claude_mods=v.cfg.vigild.github.claude_mods,
        allowed_repos=list(v.cfg.repos.repos),
    )


def build_runner(v: Vigild, app: Any) -> JobRunner:
    """The real executor, workspace and publisher behind the job service."""
    import docker

    from vigild.devimage import DockerImages
    from vigild.executors.runtime import DockerRuntime, DockerTestRunner
    from vigild.verifier import Verifier
    from vigild.github.app import READ_ONLY
    from vigild.jobs.runner import GitHubPublisher, NoPublisher, Publisher
    from vigild.workspace import Workspace

    client = docker.from_env()

    @contextmanager
    def read_token(repo: str) -> Iterator[str | None]:
        """Mirror fetches use a read-scoped App token, never host credentials (item 22)."""
        with app.lease(repo, dict(READ_ONLY)) as tok:
            yield tok.token

    ws = Workspace(v.cfg.vigild.data_path, token_for=read_token)
    publisher: Publisher = GitHubPublisher(app, app.http, ws) if app else NoPublisher()
    runtime = DockerRuntime(v.cfg, client)
    runner = JobRunner(
        v.cfg,
        v.store,
        v.budget,
        v.gateway,
        runtime,
        ws,
        publisher,
        v.telemetry,
        DevImages(v.cfg, v.store, DockerImages(client, v.cfg.vigild.container.uid)),
        Verifier(ws, DockerTestRunner(v.cfg, client)),
        reaper=runtime.reap,
    )
    runner.jobs = v.services.jobs
    return runner


def validate_images_forever(images: DevImages, stop: threading.Event) -> None:
    """Dev images are validated at start and every 24 hours by vigild itself
    (item 21): one way to do it, no launchd job."""
    while not stop.is_set():
        for repo in images.cfg.repos.repos:
            if images.due(repo):
                v = images.validate(repo)
                log.info("dev image %s for %s: %s", v.image, repo, "ok" if v.ok else "FAILED")
        stop.wait(3600)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from vigild.repos import RepoPolicyError, verify_visibility

    v = build()
    app = _github_app(v)
    if app is None:
        raise SystemExit(
            "vigild: the GitHub App isn't configured, so repo visibility can't be "
            "verified; refusing to start (GITHUB_APP_ID, GITHUB_APP_KEY_PATH)"
        )
    try:
        verify_visibility(v.cfg, app.is_private)
    except RepoPolicyError as e:
        raise SystemExit(f"vigild: {e}") from e
    runner = build_runner(v, app)
    v.services.jobs.runner = runner
    log.info("reconcile: %s", runner.reconcile())
    stop = threading.Event()
    threading.Thread(
        target=validate_images_forever, args=(runner.dev_images, stop), daemon=True
    ).start()
    asyncio.run(serve(v))

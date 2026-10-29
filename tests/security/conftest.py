"""Security tests start real worker containers (pytest -m docker, on the Mac).
Images: `uv run python scripts/build-images.py`."""

from __future__ import annotations

import contextlib
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from vigild.config import Config
from vigild.executors.base import SessionSpec
from vigild.executors.runtime import DockerRuntime
from vigild.jobs.model import Role
from vigild.workspace import Workspace


def _docker() -> object:
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return client
    except Exception as e:
        pytest.fail(f"Docker is not reachable: {e}")


@pytest.fixture
def runtime(cfg: Config) -> DockerRuntime:
    client = _docker()
    for image in (cfg.vigild.images.claude_executor, cfg.vigild.images.egress_proxy):
        try:
            client.images.get(image)  # type: ignore[attr-defined]
        except Exception:
            pytest.fail(f"{image} is not built; run scripts/build-images.py")
    return DockerRuntime(cfg, client)


RUN_LABEL = "vigil.test-run"
SESSION_LABEL = "dev.vigil.session"

LAYERED = ("parkagent", "vigil")


def _latest_session_image(name: str) -> str:
    """The `vigil-session/<name>` image built from the executor layer as it is
    now (round 4, item 11): its layer label is today's `layer_digest()`."""
    from vigild.devimage import LAYER_LABEL, layer_digest

    client = _docker()
    want = layer_digest()
    tags = [
        t
        for img in client.images.list(name=f"vigil-session/{name}")  # type: ignore[attr-defined]
        if (img.labels or {}).get(LAYER_LABEL) == want
        for t in img.tags
    ]
    if not tags:
        pytest.fail(
            f"no vigil-session/{name} image from the current executor layer: run "
            f"`vigil dev-image --repo .../{name}`"
        )
    return sorted(tags)[-1]


@pytest.fixture(params=["generic", *LAYERED])
def executor_image(request: pytest.FixtureRequest, cfg: Config) -> str:
    """Owner direction, round 3: the threat rows run against the generic
    executor image and against the layered ParkAgent and vigil session images."""
    if request.param == "generic":
        return cfg.vigild.images.claude_executor
    return _latest_session_image(request.param)


@pytest.fixture
def make_spec(
    tmp_path: Path, fixture_repo: dict[str, Path], cfg: Config, executor_image: str
) -> Callable[..., SessionSpec]:
    # Docker Desktop shares /private; keep paths short for socket limits.
    ws = Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"]))
    n = [0]
    made: list[str] = []
    run_id = uuid.uuid4().hex

    def make(role: Role = Role.WORKER) -> SessionSpec:
        n[0] += 1
        sid = f"s-sec{tmp_path.name[-6:].lower().replace('_', '')}{n[0]}"
        made.append(sid)
        clone = ws.clone(
            "o/fixture", f"fx-0001-w{n[0]}", branch=f"vigil/fx-0001-w{n[0]}", base="main"
        )
        ws.write_task(
            clone,
            {
                "task_id": f"fx-0001-w{n[0]}",
                "job_id": "fx-0001",
                "branch": f"vigil/fx-0001-w{n[0]}",
                "base_sha": ws.base_sha(f"fx-0001-w{n[0]}"),
                "spec": {},
            },
        )
        return SessionSpec(
            session_id=sid,
            role=role,
            job_id="fx-0001",
            task_id=f"fx-0001-w{n[0]}",
            repo="thomasbardhi01/vigil",
            preset="claude-haiku",
            model="claude-haiku-5-5",
            clone=clone,
            session_dir=tmp_path / "sessions" / sid,
            max_turns=5,
            max_minutes=5,
            max_budget_usd=0.05,
            mounts=ws.overlays(clone),
            packet="(probe)",
            image=executor_image,
        )

    try:
        yield make
    finally:
        # a session id repeats from run to run, so a network a test left behind makes the
        # next run's create fail with 409: remove what this run made, by label
        _teardown_run(_docker(), session_ids=made, run_id=run_id)
        shutil.rmtree(tmp_path / "data", ignore_errors=True)


def _teardown_run(client: Any, *, session_ids: list[str], run_id: str) -> None:
    """Remove only what this run made, selected by label (never by name or by
    network membership). A container on a run network that lacks this run's
    label is disconnected, not removed (Phase 1 finding #5)."""
    selectors = [f"{SESSION_LABEL}={sid}" for sid in session_ids] + [f"{RUN_LABEL}={run_id}"]
    mine = set(session_ids)

    def is_mine(labels: dict[str, str] | None) -> bool:
        labels = labels or {}
        return labels.get(RUN_LABEL) == run_id or labels.get(SESSION_LABEL) in mine

    for sel in selectors:
        for c in client.containers.list(all=True, filters={"label": sel}):
            with contextlib.suppress(Exception):  # NotFound: already gone
                c.remove(force=True)
    for sel in selectors:
        for net in client.networks.list(filters={"label": sel}):
            with contextlib.suppress(Exception):
                net.reload()
                for c in list(net.containers):
                    if not is_mine(c.labels):
                        net.disconnect(c, force=True)
                net.remove()

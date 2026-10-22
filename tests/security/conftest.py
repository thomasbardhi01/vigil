"""Security tests start real worker containers (pytest -m docker, on the Mac).
Images: `uv run python scripts/build-images.py`."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

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


@pytest.fixture
def make_spec(
    tmp_path: Path, fixture_repo: dict[str, Path], cfg: Config
) -> Callable[..., SessionSpec]:
    # Docker Desktop shares /private; keep paths short for socket limits.
    ws = Workspace(tmp_path / "data", remote_url=lambda r: str(fixture_repo["bare"]))
    n = [0]

    def make(role: Role = Role.WORKER) -> SessionSpec:
        n[0] += 1
        sid = f"s-sec{tmp_path.name[-6:].lower().replace('_', '')}{n[0]}"
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
        )

    yield make
    shutil.rmtree(tmp_path / "data", ignore_errors=True)

"""One value decides the gateway port (VIGIL_GATEWAY_PORT); the default is 8788."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vigild import config
from vigild.config import Config, ConfigError
from vigild.executors.base import SessionSpec
from vigild.executors.egress import proxy_config_yaml
from vigild.executors.runtime import worker_kwargs
from vigild.jobs.model import Role


def _spec(tmp_path: Path) -> SessionSpec:
    return SessionSpec(
        session_id="s-1", role=Role.WORKER, job_id="j", task_id="t", repo="o/r", preset="p",
        model="m", clone=tmp_path / "c", session_dir=tmp_path / "s", max_turns=1,
        max_minutes=1, max_budget_usd=1.0,
    )  # fmt: skip


def _check(cfg: Config, tmp_path: Path, port: int) -> None:
    assert cfg.vigild.gateway.port == port
    assert cfg.egress.gateway.port == port
    assert cfg.egress.gateway.allow_address == f"192.168.65.254:{port}"
    assert yaml.safe_load(proxy_config_yaml(cfg))["allow_addresses"] == [f"192.168.65.254:{port}"]
    host = cfg.sandbox_hosts.local
    assert host.gateway_url == f"http://host.docker.internal:{port}"
    env = worker_kwargs(cfg, _spec(tmp_path), network="n", host=host)["environment"]
    assert env["VIGIL_GATEWAY_URL"] == f"http://host.docker.internal:{port}"


def test_default_is_8788_everywhere(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VIGIL_GATEWAY_PORT", raising=False)
    _check(config.load(), tmp_path, 8788)


def test_env_override_derives_everything(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("VIGIL_GATEWAY_PORT", "49999")
    _check(config.load(), tmp_path, 49999)


def test_apply_gateway_port_on_a_loaded_config(tmp_path: Path) -> None:
    c = config.load()
    config.apply_gateway_port(c, 49999)
    _check(c, tmp_path, 49999)


def test_remote_host_gateway_url_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIGIL_GATEWAY_PORT", "49999")
    c = config.load()
    assert all(h.gateway_url.endswith(":49999") for h in c.sandbox_hosts.hosts if not h.remote)


@pytest.mark.parametrize("bad", ["abc", "0", "65536", "-1", "80.5"])
def test_invalid_override_is_refused(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("VIGIL_GATEWAY_PORT", bad)
    with pytest.raises(ConfigError):
        config.load()


@pytest.mark.parametrize("bad", [0, 65536, -5])
def test_apply_refuses_an_invalid_port(bad: int) -> None:
    with pytest.raises(ConfigError):
        config.apply_gateway_port(config.load(), bad)

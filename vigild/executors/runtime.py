"""Container lifecycle (B4, B5, B17, B18): one hardened container per session,
on its own internal network, with a smokescreen sidecar as its only way out
and the OTel collector attached while it runs.

`worker_kwargs` and `proxy_kwargs` are pure, so the hardening is unit-tested
without Docker; `DockerRuntime` runs them (tests/security/ runs it for real).
"""

from __future__ import annotations

import contextlib
import json
import shutil
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from vigild.config import Config
from vigild.executors.base import EventSink, ExecOutcome, SessionSpec
from vigild.executors.egress import acl_yaml, allowlist, proxy_config_yaml

LABEL = "dev.vigil.session"


def _hardening(cfg: Config) -> dict[str, Any]:
    return {
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges"],
        "pids_limit": cfg.vigild.container.pids_limit,
        "mem_limit": cfg.vigild.container.memory,
        "privileged": False,
    }


def _mount(source: str, target: str, read_only: bool) -> dict[str, Any]:
    return {"Target": target, "Source": source, "Type": "bind", "ReadOnly": read_only}


def worker_kwargs(cfg: Config, spec: SessionSpec, *, network: str) -> dict[str, Any]:
    uid = cfg.vigild.container.uid
    col = cfg.egress.collector
    proxy = f"http://{cfg.egress.proxy.alias}:{cfg.egress.proxy.port}"
    attrs = {
        "vigil.session_id": spec.session_id,
        "vigil.job_id": spec.job_id,
        "vigil.task_id": spec.task_id or "",
        "vigil.role": spec.role.value,
        "vigil.repo": spec.repo,
        "vigil.backend": spec.preset,
        "openinference.project.name": "vigil",
    }
    env = {
        "VIGIL_ROLE": spec.role.value,
        "VIGIL_MODEL": spec.model,
        "VIGIL_GATEWAY_URL": f"http://{cfg.egress.gateway.host}:{cfg.egress.gateway.port}",
        "VIGIL_MAX_TURNS": str(spec.max_turns),
        "VIGIL_MAX_BUDGET_USD": str(spec.max_budget_usd),
        "VIGIL_REQUIRE_PLUGIN": "guard",
        "HTTP_PROXY": proxy,
        "HTTPS_PROXY": proxy,
        "NO_PROXY": f"{col.host},localhost,127.0.0.1",
        "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://{col.host}:{col.port}",
        "OTEL_SERVICE_NAME": f"vigil-{spec.role.value}",
        "OTEL_RESOURCE_ATTRIBUTES": ",".join(f"{k}={v}" for k, v in attrs.items()),
    }
    if spec.traceparent:
        env["TRACEPARENT"] = spec.traceparent
    mounts = [
        _mount(str(spec.clone), "/work", read_only=False),
        _mount(str(spec.session_dir / "packet.md"), "/vigil/packet.md", read_only=True),
        # The harness's result: the branch as a git bundle and its test record.
        # vigild reads them with safe_read_bytes; host git never touches /work.
        _mount(str(spec.session_dir / "out"), "/vigil/out", read_only=False),
        *[_mount(m.host, m.container, m.read_only) for m in spec.mounts],
    ]
    return {
        "image": spec.image or cfg.vigild.images.claude_executor,
        "name": f"vigil-{spec.session_id}",
        "user": f"{uid}:{uid}",
        "network": network,
        "environment": env,
        "mounts": mounts,
        "tmpfs": {"/tmp": f"rw,size=1g,uid={uid},gid={uid},mode=1777"},  # noqa: S108
        "stdin_open": True,
        "labels": {LABEL: spec.session_id, "dev.vigil.role": spec.role.value},
        "working_dir": "/work",
        **_hardening(cfg),
    }


def proxy_kwargs(cfg: Config, spec: SessionSpec) -> dict[str, Any]:
    return {
        "image": cfg.vigild.images.egress_proxy,
        "name": f"vigil-{spec.session_id}-egress",
        "command": ["--config-file=/etc/smokescreen/config.yaml"],
        "mounts": [_mount(str(spec.session_dir / "proxy"), "/etc/smokescreen", read_only=True)],
        "network": "bridge",
        "labels": {LABEL: spec.session_id, "dev.vigil.role": "egress"},
        **_hardening(cfg),
        "mem_limit": "128m",
        "pids_limit": 64,
    }


def write_session_files(cfg: Config, spec: SessionSpec) -> None:
    sd = spec.session_dir
    (sd / "proxy").mkdir(parents=True, exist_ok=True)
    if (sd / "out").exists():
        shutil.rmtree(sd / "out")
    (sd / "out").mkdir()
    (sd / "out").chmod(0o777)
    (sd / "packet.md").write_text(spec.packet)
    (sd / "proxy" / "acl.yaml").write_text(acl_yaml(allowlist(cfg, spec.role)))
    (sd / "proxy" / "config.yaml").write_text(proxy_config_yaml(cfg))
    for p in (sd, sd / "proxy"):
        p.chmod(0o755)
    for f in (sd / "packet.md", sd / "proxy" / "acl.yaml", sd / "proxy" / "config.yaml"):
        f.chmod(0o644)


def _docker_mounts(raw: list[dict[str, Any]]) -> list[Any]:
    import docker.types

    return [
        docker.types.Mount(m["Target"], m["Source"], type="bind", read_only=m["ReadOnly"])
        for m in raw
    ]


class DockerRuntime:
    def __init__(self, cfg: Config, client: Any = None) -> None:
        import docker

        self.cfg = cfg
        self.client = client or docker.from_env()

    @contextmanager
    def _network(self, spec: SessionSpec, on_event: EventSink) -> Iterator[str]:
        """The session's internal network, its egress sidecar and the collector."""
        import docker.errors

        write_session_files(self.cfg, spec)
        net_name = f"vigil-{spec.session_id}"
        net = self.client.networks.create(
            net_name, driver="bridge", internal=True, labels={LABEL: spec.session_id}
        )
        proxy = collector = None
        try:
            pk = proxy_kwargs(self.cfg, spec)
            pk["mounts"] = _docker_mounts(pk["mounts"])
            proxy = self.client.containers.run(detach=True, **pk)
            net.connect(proxy, aliases=[self.cfg.egress.proxy.alias])
            try:
                collector = self.client.containers.get(self.cfg.vigild.collector.container)
                net.connect(collector, aliases=[self.cfg.egress.collector.host])
            except docker.errors.NotFound:
                collector = None
                on_event({"type": "state", "data": {"collector": "not running; no traces"}})
            yield net_name
        finally:
            if proxy is not None:
                with suppress(docker.errors.APIError):
                    proxy.remove(force=True)
            if collector is not None:
                with suppress(docker.errors.APIError):
                    net.disconnect(collector, force=True)
            with suppress(docker.errors.APIError):
                net.remove()

    def run(self, spec: SessionSpec, gateway_token: str, on_event: EventSink) -> ExecOutcome:
        import docker.errors

        with self._network(spec, on_event) as net_name:
            wk = worker_kwargs(self.cfg, spec, network=net_name)
            wk["mounts"] = _docker_mounts(wk["mounts"])
            worker = self.client.containers.create(**wk)
            try:
                sock = worker.attach_socket(params={"stdin": 1, "stream": 1})
                worker.start()
                raw_sock = getattr(sock, "_sock", sock)
                raw_sock.sendall((json.dumps({"gateway_token": gateway_token}) + "\n").encode())
                with suppress(OSError):
                    raw_sock.shutdown(socket.SHUT_WR)
                sock.close()
                return self._follow(worker, spec, on_event)
            finally:
                with suppress(docker.errors.APIError):
                    worker.remove(force=True)

    def probe(self, spec: SessionSpec, command: str, timeout: int = 120) -> tuple[int, str]:
        """Run `command` in the session's exact container, network and proxy,
        instead of the harness. The security tests and `vigil doctor` use it."""
        import docker.errors

        with self._network(spec, lambda e: None) as net_name:
            wk = worker_kwargs(self.cfg, spec, network=net_name)
            wk["mounts"] = _docker_mounts(wk["mounts"])
            wk.update(entrypoint=["sh", "-c"], command=[command], stdin_open=False)
            worker = self.client.containers.create(**wk)
            try:
                worker.start()
                code = int(worker.wait(timeout=timeout).get("StatusCode", -1))
                out = worker.logs(stdout=True, stderr=True).decode(errors="replace")
                return code, out
            finally:
                with suppress(docker.errors.APIError):
                    worker.remove(force=True)

    def reap(self) -> int:
        """At startup: remove every container and network a session left behind."""
        n = 0
        for c in self.client.containers.list(all=True, filters={"label": LABEL}):
            with contextlib.suppress(Exception):
                c.remove(force=True)
                n += 1
        for net in self.client.networks.list(filters={"label": LABEL}):
            with contextlib.suppress(Exception):
                net.remove()
        return n

    def _follow(self, worker: Any, spec: SessionSpec, on_event: EventSink) -> ExecOutcome:
        timed_out = threading.Event()

        def _kill() -> None:
            timed_out.set()
            with contextlib.suppress(Exception):  # it may already have exited
                worker.kill()

        timer = threading.Timer(spec.max_minutes * 60, _kill)
        timer.start()
        result: dict[str, Any] = {}
        buf = b""
        try:
            for chunk in worker.logs(stream=True, follow=True, stdout=True, stderr=False):
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "vigil_event" in msg:
                        on_event(msg["vigil_event"])
                    elif "vigil_result" in msg:
                        result = msg["vigil_result"]
            code = int(worker.wait().get("StatusCode", -1))
        finally:
            timer.cancel()
        stderr = worker.logs(stdout=False, stderr=True, tail=40).decode(errors="replace")
        if timed_out.is_set():
            return ExecOutcome("timeout", code, result, f"over {spec.max_minutes} min")
        if code != 0 or result.get("status") != "done":
            return ExecOutcome("failed", code, result, result.get("error") or stderr[-2000:])
        return ExecOutcome("done", code, result)


def session_dir(cfg: Config, session_id: str) -> Path:
    return cfg.vigild.data_path / "sessions" / session_id

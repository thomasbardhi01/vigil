"""Kill through the real executor class (#160): the runner's executor is a `HostExecutor`,
and a kill reaches the session's two containers (worker and egress sidecar) and its network
through it. Before the fix `HostExecutor` had no `stop_job` / `purge_job`, so the runner
(`getattr(executor, "stop_job", None)`) skipped the containers silently, reported
`containers_removed: 0` and left them up until the worker gave up on its own."""

# ruff: noqa: F811  (fixtures imported from the modules that define them)

from __future__ import annotations

import threading
from typing import Any

from tests.jobs.test_coord_loop import World, _request, auth, world  # noqa: F401
from tests.jobs.test_kill import Hung, _kill, _spec_item
from vigild.config import Config
from vigild.executors.base import EventSink, ExecOutcome, SessionSpec
from vigild.executors.hosts import HostExecutor, Hosts
from vigild.executors.runtime import JOB_LABEL, LABEL
from vigild.jobs.model import Role


class Thing:
    """A container or network in the fake daemon's pool."""

    def __init__(self, pool: list[Thing], name: str, labels: dict[str, str], on_kill: Any) -> None:
        self.pool, self.name, self.labels, self.on_kill = pool, name, labels, on_kill
        self.attrs: dict[str, Any] = {"Labels": labels, "Containers": {}}
        self.stuck = False
        self.id = name
        pool.append(self)

    def kill(self) -> None:
        self.on_kill()

    def remove(self, force: bool = False) -> None:
        if self.stuck:
            raise RuntimeError("device busy")
        if self in self.pool:
            self.pool.remove(self)

    def reload(self) -> None:
        pass

    def disconnect(self, cid: str, force: bool = False) -> None:
        pass


class Pool:
    def __init__(self) -> None:
        self.things: list[Thing] = []

    def list(self, **kw: Any) -> list[Thing]:
        assert kw["filters"]["label"] == LABEL
        return [t for t in self.things if LABEL in t.labels]


class Daemon:
    def __init__(self) -> None:
        self.containers, self.networks = Pool(), Pool()

    def names(self) -> list[str]:
        return sorted(t.name for t in self.containers.things + self.networks.things)


class OnHosts(Hung):
    """Hung's worker, but the kill hooks are the real `HostExecutor`'s over a fake daemon,
    and the worker "starts" the session's two containers and network as `run` does."""

    daemon: Daemon
    hostexec: HostExecutor
    stuck_egress = False

    def run(self, spec: SessionSpec, gateway_token: str, on_event: EventSink) -> ExecOutcome:
        if spec.role is Role.WORKER:
            lab = {LABEL: spec.session_id, JOB_LABEL: spec.job_id}
            Thing(self.daemon.networks.things, f"vigil-{spec.session_id}", lab, self.stopped.set)
            Thing(self.daemon.containers.things, f"vigil-{spec.session_id}", lab, self.stopped.set)
            egress = Thing(
                self.daemon.containers.things,
                f"vigil-{spec.session_id}-egress",
                lab,
                self.stopped.set,
            )
            egress.stuck = self.stuck_egress
        return super().run(spec, gateway_token, on_event)

    def stop_job(self, job_id: str, session_ids: list[str]) -> int:
        return self.hostexec.stop_job(job_id, session_ids)

    def purge_job(self, job_id: str, session_ids: list[str]) -> dict[str, Any]:
        return self.hostexec.purge_job(job_id, session_ids)


def _running(w: World, cfg: Config, *, stuck_egress: bool = False) -> Any:
    daemon = Daemon()
    hosts = Hosts(cfg, make_client=lambda h: daemon)
    hung = OnHosts(w.standin, want=1)
    hung.daemon, hung.hostexec, hung.stuck_egress = daemon, HostExecutor(hosts), stuck_egress
    w.runner.executor = hung
    job = _request(w)
    item = _spec_item(w)
    t = threading.Thread(
        target=lambda: w.client.post(
            f"/api/inbox/{item['id']}/approve", headers=auth(w.tokens.admin), json={}
        ),
        daemon=True,
    )
    t.start()
    assert hung.ready.wait(20), "the worker should be running"
    return job, hung, daemon, t


def test_kill_removes_both_containers_and_the_network_and_ends_the_session(
    world: World, cfg: Config
) -> None:
    w = world
    job, hung, daemon, t = _running(w, cfg)
    (sid,) = hung.entered
    assert daemon.names() == [f"vigil-{sid}", f"vigil-{sid}", f"vigil-{sid}-egress"]
    body = _kill(w, job).json()
    t.join(20)
    assert body["containers_removed"] == 2 and body["networks_removed"] == 1, body
    assert body["containers_failed"] == []
    assert sid in body["sessions_stopped"]
    assert daemon.names() == [], "nothing of the session is left"
    (row,) = [s for s in w.store.list_sessions(job) if s.id == sid]
    assert row.status == "killed" and row.ended_at


def test_a_container_that_will_not_go_is_named_and_its_session_not_called_stopped(
    world: World, cfg: Config
) -> None:
    w = world
    job, hung, _daemon, t = _running(w, cfg, stuck_egress=True)
    (sid,) = hung.entered
    body = _kill(w, job).json()
    t.join(20)
    assert body["containers_failed"] == [f"vigil-{sid}-egress"]
    assert body["containers_removed"] == 1
    assert sid not in body["sessions_stopped"]

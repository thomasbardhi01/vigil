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
from vigild.config import Config, SandboxHost
from vigild.executors.base import EventSink, ExecOutcome, SessionSpec
from vigild.executors.hosts import HostExecutor, Hosts
from vigild.executors.runtime import JOB_LABEL, LABEL, instance_labels
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
    stuck_verifier = False

    def run(self, spec: SessionSpec, gateway_token: str, on_event: EventSink) -> ExecOutcome:
        if spec.role is Role.WORKER:
            lab = {
                LABEL: spec.session_id,
                JOB_LABEL: spec.job_id,
                **instance_labels(self.hostexec.hosts.cfg),
            }
            Thing(self.daemon.networks.things, f"vigil-{spec.session_id}", lab, self.stopped.set)
            Thing(self.daemon.containers.things, f"vigil-{spec.session_id}", lab, self.stopped.set)
            egress = Thing(
                self.daemon.containers.things,
                f"vigil-{spec.session_id}-egress",
                lab,
                self.stopped.set,
            )
            egress.stuck = self.stuck_egress
            if self.stuck_verifier:  # a verifier checkout of the job: no session id in its name
                v = Thing(
                    self.daemon.containers.things,
                    "frosty_curie",
                    {**lab, LABEL: "verify-pa-1-w1-base-ab12"},
                    self.stopped.set,
                )
                v.stuck = True
        return super().run(spec, gateway_token, on_event)

    def stop_job(self, job_id: str, session_ids: list[str]) -> int:
        return self.hostexec.stop_job(job_id, session_ids)

    def purge_job(self, job_id: str, session_ids: list[str]) -> dict[str, Any]:
        return self.hostexec.purge_job(job_id, session_ids)


def _running(
    w: World, cfg: Config, *, stuck_egress: bool = False, stuck_verifier: bool = False
) -> Any:
    daemon = Daemon()
    hosts = Hosts(cfg, make_client=lambda h: daemon)
    hung = OnHosts(w.standin, want=1)
    hung.daemon, hung.hostexec, hung.stuck_egress = daemon, HostExecutor(hosts), stuck_egress
    hung.stuck_verifier = stuck_verifier
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


def test_a_stuck_verifier_container_makes_the_kill_unclean_and_is_named(
    world: World, cfg: Config
) -> None:
    w = world
    job, hung, _daemon, t = _running(w, cfg, stuck_verifier=True)
    (sid,) = hung.entered
    body = _kill(w, job).json()
    t.join(20)
    assert body["containers_failed"] == ["frosty_curie"]
    assert body["clean"] is False
    assert sid in body["sessions_stopped"], "the session's own containers did go"


def test_a_kill_with_nothing_stuck_is_clean(world: World, cfg: Config) -> None:
    w = world
    job, _hung, _daemon, t = _running(w, cfg)
    body = _kill(w, job).json()
    t.join(20)
    assert body["clean"] is True and body["hosts_unreachable"] == []
    assert body["unowned"] == []


def test_an_inbox_abandon_removes_the_jobs_leftover_containers_like_a_kill(
    world: World, cfg: Config
) -> None:
    """The FSM lets the inbox abandon only a job that is not building, but such a job may
    still have a verifier or deps container up; abandoning stops and purges them."""
    w = world
    daemon = Daemon()
    hostexec = HostExecutor(Hosts(cfg, make_client=lambda h: daemon))

    class Ex:  # the usual stand-in runs; the kill hooks are the real HostExecutor's
        def __getattr__(self, name: str) -> Any:
            return getattr(w.standin, name)

        def stop_job(self, job_id: str, session_ids: list[str]) -> int:
            return hostexec.stop_job(job_id, session_ids)

        def purge_job(self, job_id: str, session_ids: list[str]) -> dict[str, Any]:
            return hostexec.purge_job(job_id, session_ids)

    w.runner.executor = Ex()
    job = _request(w)
    lab = {LABEL: "verify-pa-1-w1-base-ab12", JOB_LABEL: job, **instance_labels(cfg)}
    killed: list[str] = []
    Thing(daemon.containers.things, "verifier", lab, lambda: killed.append("verifier"))
    Thing(daemon.containers.things, "other", {**lab, JOB_LABEL: "vi-9999"}, lambda: None)
    item = w.runner.jobs.page(job, "p", {"actions": ["abandon"]})  # type: ignore[union-attr]
    w.runner.jobs.abandon(item.id)  # type: ignore[union-attr]
    assert set(killed) == {"verifier"}
    assert daemon.names() == ["other"], "only this job's container went"
    (ev,) = [e for e in w.store.events() if e.job_id == job and e.type == "job_killed"]
    assert ev.data["containers_removed"] == 1 and ev.data["clean"] is True


# --- every configured host, not only the ones this process has used ------------------------


def _remote(cfg: Config) -> SandboxHost:
    h = SandboxHost(
        name="gpu", docker_context="gpu", arch="amd64", memory_gb=8, cpus=4, disk_budget_gb=50,
        uses=["bench"], gateway_url="http://10.0.0.5:8788", engine_pin="27.0.0",
        private_address="10.0.0.9",
    )  # fmt: skip
    cfg.sandbox_hosts.gateway_bind = "10.0.0.5"
    cfg.sandbox_hosts.hosts.append(h)
    return h


def test_a_kill_reaches_a_remote_host_this_process_never_used(cfg: Config) -> None:
    h = _remote(cfg)
    local_d, remote_d = Daemon(), Daemon()
    mine = instance_labels(cfg)
    lab = {LABEL: "s-1", JOB_LABEL: "vi-0001", **mine}
    killed: list[str] = []
    Thing(remote_d.containers.things, "vigil-s-1", lab, lambda: killed.append("worker"))
    Thing(remote_d.networks.things, "vigil-s-1", lab, lambda: None)
    hosts = Hosts(cfg, make_client=lambda host: remote_d if host.name == h.name else local_d)
    assert hosts._runtimes == {}, "no runtime was ever built in this process"
    ex = HostExecutor(hosts)
    assert ex.stop_job("vi-0001", ["s-1"]) == 1 and killed == ["worker"]
    out = ex.purge_job("vi-0001", ["s-1"])
    assert out["containers"] == 1 and out["networks"] == 1 and out["failed"] == []
    assert out["hosts_unreachable"] == [] and remote_d.names() == []


def test_a_host_that_cannot_be_reached_is_reported_not_counted_as_success(cfg: Config) -> None:
    h = _remote(cfg)

    class Down:
        containers = networks = None

        def __getattr__(self, name: str) -> Any:
            raise ConnectionError("ssh: connect to host gpu: timed out")

    hosts = Hosts(cfg, make_client=lambda host: Down() if host.name == h.name else Daemon())
    ex = HostExecutor(hosts)
    assert ex.stop_job("vi-0001", []) == 0
    out = ex.purge_job("vi-0001", [])
    assert out["hosts_unreachable"] == ["gpu"]
    assert out["failed"] == []

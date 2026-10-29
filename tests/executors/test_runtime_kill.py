"""DockerRuntime.stop_job / purge_job pick a job's containers and networks by vigil's
labels only (issue #52): its sessions' and their egress sidecars' (by session label), its
verifier's, hidden-test probes' and deps containers' (by the job label); never another
job's, never an unlabelled one."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vigild.config import Config
from vigild.executors.base import SessionSpec
from vigild.executors.runtime import (
    INSTANCE_LABEL,
    JOB_LABEL,
    LABEL,
    DockerRuntime,
    deps_kwargs,
    instance_labels,
    job_scope,
    proxy_kwargs,
    verifier_kwargs,
)
from vigild.jobs.model import Role


class Box:
    def __init__(self, labels: dict[str, str], log: list[str], name: str) -> None:
        self.labels = labels
        self.attrs: dict[str, Any] = {"Labels": labels, "Containers": {"collector-id": {}}}
        self.name = name
        self.id = f"id-{name}"
        self.log = log
        self.home: list[Box] = []
        self.stuck = False

    def kill(self) -> None:
        self.log.append(f"kill {self.name}")

    def remove(self, force: bool = False) -> None:
        self.log.append(f"rm {self.name}")
        if self.stuck:
            raise RuntimeError("device busy")
        if self in self.home:
            self.home.remove(self)

    def reload(self) -> None:
        pass

    def disconnect(self, cid: str, force: bool = False) -> None:
        self.log.append(f"disconnect {self.name} {cid}")


class Listing:
    def __init__(self, boxes: list[Box]) -> None:
        self.boxes = boxes
        for b in boxes:
            b.home = boxes

    def list(self, **kw: Any) -> list[Box]:
        key = kw["filters"]["label"]
        assert key == LABEL, "list by the label's key, then match its value ourselves"
        return [b for b in self.boxes if LABEL in b.labels]


class Client:
    def __init__(self, containers: list[Box], networks: list[Box]) -> None:
        self.containers = Listing(containers)
        self.networks = Listing(networks)


def _world(cfg: Config) -> tuple[DockerRuntime, list[str]]:
    log: list[str] = []

    mine = instance_labels(cfg)

    def box(name: str, value: str | None, job: str | None = None) -> Box:
        labels = {LABEL: value, **mine} if value else {"other": "x"}
        if job:
            labels[JOB_LABEL] = job
        return Box(labels, log, name)

    containers = [
        box("worker", "s-mine", "job-mine"), box("sidecar", "s-mine", "job-mine"),
        box("verifier", "verify-pa-1-w1-base-ab12", "job-mine"),
        box("probe", "verify-probe-ab12cd34-xy", "job-mine"),  # a hidden-test author's probe
        box("deps", "deps-0123456789ab", "job-mine"),
        box("deps-sidecar", "deps-0123456789ab", "job-mine"),
        box("other-worker", "s-theirs", "job-theirs"),
        box("other-verifier", "verify-pa-2-w1-base-cd34", "job-theirs"),
        box("other-probe", "verify-probe-ab12cd34-zz", "job-theirs"),  # same name, other job
        box("other-deps", "deps-ba9876543210", "job-theirs"),
        box("no-job-label", "verify-pa-1-w1-after-ef56"),  # named for the job's task: not ours
        box("unlabelled", None),
    ]  # fmt: skip
    networks = [
        box("net-mine", "s-mine", "job-mine"), box("net-deps", "deps-0123456789ab", "job-mine"),
        box("net-theirs", "s-theirs", "job-theirs"), box("net-deps-theirs", "deps-ba9876543210", "job-theirs"),
        box("net-none", None),
    ]  # fmt: skip
    return DockerRuntime(cfg, Client(containers, networks)), log


def test_stop_job_kills_only_the_jobs_containers(cfg: Config) -> None:
    rt, log = _world(cfg)
    n = rt.stop_job("job-mine", ["s-mine"])
    assert sorted(log) == [
        "kill deps", "kill deps-sidecar", "kill probe", "kill sidecar", "kill verifier",
        "kill worker",
    ]  # fmt: skip
    assert n == 6


def test_purge_job_removes_only_the_jobs_containers_and_networks(cfg: Config) -> None:
    rt, log = _world(cfg)
    out = rt.purge_job("job-mine", ["s-mine"])
    assert (out["containers"], out["networks"], out["failed"]) == (6, 2, [])
    assert sorted(x for x in log if x.startswith("rm ")) == [
        "rm deps", "rm deps-sidecar", "rm net-deps", "rm net-mine", "rm probe", "rm sidecar",
        "rm verifier", "rm worker",
    ]  # fmt: skip
    # the shared collector is let go of before the network goes
    assert "disconnect net-mine collector-id" in log


def test_a_job_with_nothing_matches_nothing(cfg: Config) -> None:
    rt, log = _world(cfg)
    assert rt.stop_job("job-none", []) == 0
    out = rt.purge_job("job-none", [])
    assert (out["containers"], out["networks"], out["failed"]) == (0, 0, [])
    assert log == []


def test_a_deps_container_is_stopped_by_its_jobs_kill_and_no_other_jobs(cfg: Config) -> None:
    rt, log = _world(cfg)
    rt.stop_job("job-theirs", [])
    assert "kill deps" not in log and "kill other-deps" in log
    assert "kill probe" not in log and "kill other-probe" in log


def test_the_containers_a_job_starts_carry_its_label(cfg: Config, tmp_path: Path) -> None:
    """The label the kill selects by is put on every container vigild starts for a job
    outside a session: verifier checkouts, hidden-test probes (both are `verifier_kwargs`)
    and deps builds, and on a session's sidecar; with no job in scope there is none."""
    plain = verifier_kwargs(cfg, "img", tmp_path, "true", None, None, None)
    assert JOB_LABEL not in plain["labels"]
    with job_scope("job-7"):
        v = verifier_kwargs(cfg, "img", tmp_path, "true", None, None, None)
        d = deps_kwargs(cfg, "img", tmp_path, network="n")
    assert v["labels"][JOB_LABEL] == "job-7" and d["labels"][JOB_LABEL] == "job-7"
    assert (
        JOB_LABEL not in verifier_kwargs(cfg, "img", tmp_path, "true", None, None, None)["labels"]
    )
    spec = SessionSpec(
        session_id="s-1", role=Role.WORKER, job_id="job-7", task_id=None, repo="o/r",
        preset="p", model="m", clone=tmp_path, session_dir=tmp_path, max_turns=1,
        max_minutes=1, max_budget_usd=0.1,
    )  # fmt: skip
    assert proxy_kwargs(cfg, spec)["labels"][JOB_LABEL] == "job-7"


def test_purge_counts_what_the_kill_stopped_though_run_removed_it_first(cfg: Config) -> None:
    rt, _log = _world(cfg)
    rt.stop_job("job-mine", ["s-mine"])
    for b in rt.client.containers.boxes[:]:
        if b.name in ("worker", "sidecar"):
            b.remove()  # the session's own `run` cleaning up after the kill
    out = rt.purge_job("job-mine", ["s-mine"])
    assert out["containers"] == 6 and out["failed"] == []


def test_a_container_that_will_not_go_is_named(cfg: Config) -> None:
    rt, _log = _world(cfg)
    (sidecar,) = [b for b in rt.client.containers.boxes if b.name == "sidecar"]
    sidecar.stuck = True
    out = rt.purge_job("job-mine", ["s-mine"])
    assert out["failed"] == ["sidecar"] and out["containers"] == 5


def test_every_container_vigild_starts_carries_its_instance_label(
    cfg: Config, tmp_path: Path
) -> None:
    mine = instance_labels(cfg)
    assert list(mine) == [INSTANCE_LABEL]
    with job_scope("job-7"):
        v = verifier_kwargs(cfg, "img", tmp_path, "true", None, None, None)
        d = deps_kwargs(cfg, "img", tmp_path, network="n")
    spec = SessionSpec(
        session_id="s-1", role=Role.WORKER, job_id="job-7", task_id=None, repo="o/r",
        preset="p", model="m", clone=tmp_path, session_dir=tmp_path, max_turns=1,
        max_minutes=1, max_budget_usd=0.1,
    )  # fmt: skip
    for labels in (v["labels"], d["labels"], proxy_kwargs(cfg, spec)["labels"]):
        assert labels[INSTANCE_LABEL] == mine[INSTANCE_LABEL]


def test_another_vigilds_containers_with_the_same_job_id_are_left_alone(
    cfg: Config, tmp_path: Path
) -> None:
    """Job ids are per-database counters: two vigilds (production and a scratch data dir)
    both have a `vi-0001`. A kill in one never touches the other's containers."""
    log: list[str] = []
    cfg2 = cfg.model_copy(deep=True)
    cfg2.vigild.data_dir = str(tmp_path / "other-data")
    a, b = instance_labels(cfg), instance_labels(cfg2)
    assert a != b
    boxes = [
        Box({LABEL: "s-a", JOB_LABEL: "vi-0001", **a}, log, "a-worker"),
        Box({LABEL: "verify-x", JOB_LABEL: "vi-0001", **a}, log, "a-verifier"),
        Box({LABEL: "s-b", JOB_LABEL: "vi-0001", **b}, log, "b-worker"),
        Box({LABEL: "verify-y", JOB_LABEL: "vi-0001", **b}, log, "b-verifier"),
    ]
    nets = [Box({LABEL: "s-a", JOB_LABEL: "vi-0001", **a}, log, "a-net"),
            Box({LABEL: "s-b", JOB_LABEL: "vi-0001", **b}, log, "b-net")]  # fmt: skip
    client = Client(boxes, nets)
    rt_a, rt_b = DockerRuntime(cfg, client), DockerRuntime(cfg2, client)
    assert rt_a.stop_job("vi-0001", ["s-a", "s-b"]) == 2
    assert sorted(log) == ["kill a-verifier", "kill a-worker"]
    out = rt_a.purge_job("vi-0001", ["s-a", "s-b"])  # a session id of b's is not a's either
    assert out["failed"] == [] and out["containers"] == 2 and out["networks"] == 1
    assert sorted(x.name for x in client.containers.boxes) == ["b-verifier", "b-worker"]
    assert [x.name for x in client.networks.boxes] == ["b-net"]
    log.clear()
    assert rt_b.stop_job("vi-0001", ["s-b"]) == 2


def test_a_pre_label_container_goes_only_if_its_id_was_recorded(cfg: Config) -> None:
    """Before the instance label there was none. Such a container is removed only when its
    Docker id is among those vigild recorded for the job; otherwise it is left and listed
    as `unowned`. Other jobs' pre-label containers are not even listed."""
    log: list[str] = []
    boxes = [
        Box({LABEL: "s-mine", JOB_LABEL: "vi-1"}, log, "recorded-worker"),
        Box({LABEL: "s-mine"}, log, "recorded-no-job-label"),
        Box({LABEL: "s-x", JOB_LABEL: "vi-1"}, log, "unrecorded"),
        Box({LABEL: "s-y", JOB_LABEL: "vi-2"}, log, "other-job"),
    ]
    ids = {"id-recorded-worker", "id-recorded-no-job-label"}
    rt = DockerRuntime(cfg, Client(boxes, []), recorded=lambda job: ids)
    assert rt.stop_job("vi-1", []) == 2
    out = rt.purge_job("vi-1", [])
    assert out["failed"] == [] and out["containers"] == 2
    assert out["unowned"] == ["unrecorded"]
    assert sorted(b.name for b in rt.client.containers.boxes) == ["other-job", "unrecorded"]


def test_a_recorded_id_is_removed_whatever_its_labels(cfg: Config) -> None:
    log: list[str] = []
    other = {INSTANCE_LABEL: "someone-else", LABEL: "s-1", JOB_LABEL: "vi-1"}
    boxes = [Box(other, log, "mine-by-id"), Box(dict(other), log, "theirs")]
    rt = DockerRuntime(cfg, Client(boxes, []), recorded=lambda job: {"id-mine-by-id"})
    out = rt.purge_job("vi-1", [])
    assert out["containers"] == 1
    assert [b.name for b in rt.client.containers.boxes] == ["theirs"]


def test_reap_leaves_another_vigilds_and_unrecorded_pre_label_containers(cfg: Config) -> None:
    log: list[str] = []
    mine = instance_labels(cfg)
    boxes = [
        Box({LABEL: "a", **mine}, log, "ours"),
        Box({LABEL: "b", INSTANCE_LABEL: "other"}, log, "theirs"),
        Box({LABEL: "c"}, log, "old-recorded"),
        Box({LABEL: "d"}, log, "old-unknown"),
    ]
    rt = DockerRuntime(cfg, Client(boxes, []), recorded=lambda job: {"id-old-recorded"})
    assert rt.reap() == 2
    assert sorted(b.name for b in boxes) == ["old-unknown", "theirs"]


def test_a_kill_error_is_recorded_not_swallowed(cfg: Config) -> None:
    rt, _log = _world(cfg)
    (worker,) = [b for b in rt.client.containers.boxes if b.name == "worker"]

    def boom() -> None:
        raise RuntimeError("cannot kill: permission denied")

    worker.kill = boom  # type: ignore[method-assign]
    worker.stuck = True
    assert rt.stop_job("job-mine", ["s-mine"]) == 5
    out = rt.purge_job("job-mine", ["s-mine"])
    assert out["failed"] == ["worker"]
    assert "permission denied" in out["kill_errors"]["worker"]


def test_a_session_records_the_ids_of_its_network_sidecar_and_worker() -> None:
    from types import SimpleNamespace

    from vigild.db import Store
    from vigild.executors.runtime import _record

    events: list[dict[str, Any]] = []
    for kind, tid in (("network", "n" * 64), ("egress", "e" * 64), ("worker", "w" * 64)):
        _record(events.append, kind, SimpleNamespace(id=tid, name=f"vigil-{kind}"))
    _record(events.append, "worker", SimpleNamespace(id="", name="x"))  # no id: nothing said
    assert [e["type"] for e in events] == ["container"] * 3
    store = Store.open(":memory:")
    for e in events:
        store.add_event(e["type"], e["data"], "claude", job_id=None)
    assert store.recorded_container_ids() == {"n" * 64, "e" * 64, "w" * 64}
    assert store.recorded_container_ids("vi-1") == set()

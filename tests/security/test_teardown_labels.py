"""_teardown_run removes only this run's labelled resources (no Docker needed)."""

from __future__ import annotations

from typing import Any

from tests.security.conftest import RUN_LABEL, SESSION_LABEL, _teardown_run


class NotFound(Exception):
    pass


class FakeContainer:
    def __init__(self, client: FakeClient, name: str, labels: dict[str, str], running: bool = True):
        self.client, self.name, self.labels, self.running = client, name, labels, running

    def remove(self, force: bool = False) -> None:
        if self.name not in self.client.containers_by_name:
            raise NotFound(self.name)
        del self.client.containers_by_name[self.name]
        for net in self.client.nets.values():
            if self in net.members:
                net.members.remove(self)
        self.client.removed.append(self.name)


class FakeNetwork:
    def __init__(self, client: FakeClient, name: str, labels: dict[str, str]):
        self.client, self.name, self.labels = client, name, labels
        self.members: list[FakeContainer] = []

    @property
    def containers(self) -> list[FakeContainer]:
        return list(self.members)

    def reload(self) -> None:
        if self.name not in self.client.nets:
            raise NotFound(self.name)

    def disconnect(self, c: FakeContainer, force: bool = False) -> None:
        if self.name not in self.client.nets or c not in self.members:
            raise NotFound(c.name)
        self.members.remove(c)
        self.client.disconnected.append(c.name)

    def remove(self) -> None:
        if self.name not in self.client.nets:
            raise NotFound(self.name)
        if self.members:
            raise RuntimeError("network has active endpoints")
        del self.client.nets[self.name]
        self.client.removed.append(self.name)


def _match(labels: dict[str, str], filters: dict[str, Any] | None) -> bool:
    sel = (filters or {}).get("label")
    if sel is None:
        return True
    k, _, v = sel.partition("=")
    return k in labels and (not v or labels[k] == v)


class _Containers:
    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def list(self, all: bool = False, filters: dict[str, Any] | None = None) -> list[Any]:
        return [
            c
            for c in self.client.containers_by_name.values()
            if (all or c.running) and _match(c.labels, filters)
        ]


class _Networks:
    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def list(self, filters: dict[str, Any] | None = None) -> list[Any]:
        return [n for n in self.client.nets.values() if _match(n.labels, filters)]


class FakeClient:
    def __init__(self) -> None:
        self.containers_by_name: dict[str, FakeContainer] = {}
        self.nets: dict[str, FakeNetwork] = {}
        self.removed: list[str] = []
        self.disconnected: list[str] = []
        self.containers = _Containers(self)
        self.networks = _Networks(self)

    def add_container(
        self, name: str, labels: dict[str, str], running: bool = True, net: str | None = None
    ) -> FakeContainer:
        c = FakeContainer(self, name, labels, running)
        self.containers_by_name[name] = c
        if net:
            self.nets[net].members.append(c)
        return c

    def add_network(self, name: str, labels: dict[str, str]) -> FakeNetwork:
        self.nets[name] = FakeNetwork(self, name, labels)
        return self.nets[name]


def _world() -> FakeClient:
    c = FakeClient()
    c.add_network("vigil-s1", {SESSION_LABEL: "s1"})
    c.add_container("worker", {SESSION_LABEL: "s1"}, net="vigil-s1")
    c.add_container("stopped", {RUN_LABEL: "run1"}, running=False)
    c.add_container("other-run", {RUN_LABEL: "run2"})
    return c


def test_removes_only_labelled_including_stopped() -> None:
    c = _world()
    _teardown_run(c, session_ids=["s1"], run_id="run1")
    assert set(c.containers_by_name) == {"other-run"}
    assert c.nets == {}


def test_foreign_container_disconnected_not_removed() -> None:
    c = _world()
    c.add_container("shared", {}, net="vigil-s1")
    _teardown_run(c, session_ids=["s1"], run_id="run1")
    assert c.disconnected == ["shared"]
    assert "shared" in c.containers_by_name
    assert "shared" in [x.name for x in c.containers.list(all=True)]
    assert "vigil-s1" not in c.nets


def test_name_match_without_label_survives() -> None:
    c = _world()
    c.add_container("vigil-s1", {})
    c.add_network("vigil-s1-extra", {})
    _teardown_run(c, session_ids=["s1"], run_id="run1")
    assert "vigil-s1" in c.containers_by_name
    assert "vigil-s1-extra" in c.nets


def test_unlabelled_vigil_sid_network_and_container_survive() -> None:
    c = FakeClient()
    c.add_network("vigil-s1", {})
    c.add_container("vigil-s1", {}, net="vigil-s1")
    c.add_network("vigil-s1-other", {SESSION_LABEL: "s9"})
    _teardown_run(c, session_ids=["s1"], run_id="run1")
    assert "vigil-s1" in c.nets
    assert "vigil-s1-other" in c.nets
    assert "vigil-s1" in c.containers_by_name
    assert c.removed == []


class _Stale:
    """list() returns a fixed snapshot, whatever happened since."""

    def __init__(self, items: list[Any]) -> None:
        self.items = items

    def list(self, **_: Any) -> list[Any]:
        return list(self.items)


def test_stale_listings_raise_nothing_and_remove_nothing_extra() -> None:
    c = _world()
    shared = c.add_container("shared", {}, net="vigil-s1")
    stale_containers = list(c.containers_by_name.values())
    stale_nets = list(c.nets.values())
    # everything vanishes between list and remove/disconnect/reload
    c.containers_by_name.clear()
    c.nets.clear()
    for n in stale_nets:
        n.members.append(shared)  # the stale net still shows the foreign member
    c.containers = _Stale(stale_containers)  # type: ignore[assignment]
    c.networks = _Stale(stale_nets)  # type: ignore[assignment]
    _teardown_run(c, session_ids=["s1"], run_id="run1")
    assert c.removed == []
    assert c.disconnected == []


def test_second_run_is_idempotent() -> None:
    c = _world()
    _teardown_run(c, session_ids=["s1"], run_id="run1")
    removed = list(c.removed)
    _teardown_run(c, session_ids=["s1"], run_id="run1")
    assert c.removed == removed


def test_empty_world_raises_nothing() -> None:
    c = FakeClient()
    _teardown_run(c, session_ids=["s1"], run_id="run1")
    assert c.removed == []

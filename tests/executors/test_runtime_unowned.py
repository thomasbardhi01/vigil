"""The shared unowned selector (#166): `find_unowned` lists vigil-labelled containers
no vigild claims; the startup reap pages them once and removes nothing more."""

from __future__ import annotations

from typing import Any

from vigild.config import Config
from vigild.db import Store
from vigild.executors.runtime import (
    INSTANCE_LABEL,
    JOB_LABEL,
    LABEL,
    DockerRuntime,
    Unowned,
    find_unowned,
    instance_labels,
)
from vigild.server import reap_and_page


class Box:
    def __init__(self, name: str, labels: dict[str, str], log: list[str]) -> None:
        self.name, self.id, self.labels, self.log = name, f"id-{name}", labels, log

    def remove(self, force: bool = False) -> None:
        self.log.append(f"rm {self.name}")


class Daemon:
    def __init__(self, cfg: Config) -> None:
        self.log: list[str] = []
        mine = instance_labels(cfg)
        other = {INSTANCE_LABEL: "someone-else"}
        boxes = [
            Box("unowned", {LABEL: "s1", JOB_LABEL: "vi-0001"}, self.log),
            Box("owned", {LABEL: "s2", JOB_LABEL: "vi-0002", **mine}, self.log),
            Box("recorded", {LABEL: "s3", JOB_LABEL: "vi-0003"}, self.log),
            Box("other", {LABEL: "s4", JOB_LABEL: "vi-0004", **other}, self.log),
        ]
        self.boxes = boxes
        self.containers = self
        self.networks = self

    def list(self, **kw: Any) -> list[Box]:
        return [b for b in self.boxes if LABEL in b.labels]


def test_selector_finds_only_what_no_vigild_claims(cfg: Config) -> None:
    d = Daemon(cfg)
    got = find_unowned(d, {"id-recorded"})
    assert got == [Unowned("unowned", "id-unowned", "vi-0001")]
    # the instance label alone does not make a pre-label container someone's
    assert [u.name for u in find_unowned(d, set())] == ["recorded", "unowned"]
    rt = DockerRuntime(cfg, d, recorded=lambda job: {"id-recorded"})
    assert rt.unowned() == got


class Runtime:
    def __init__(self, found: list[Unowned]) -> None:
        self.found, self.reaped = found, 0

    def reap(self) -> int:
        self.reaped += 1
        return 2

    def unowned(self) -> list[Unowned]:
        return self.found


class Pager:
    def __init__(self, store: Store) -> None:
        self.store, self.calls = store, 0

    def page(self, job_id: Any, title: str, body: dict[str, Any], **kw: Any) -> Any:
        self.calls += 1
        return self.store.create_inbox_item("questions", "page", job_id, title, body)


def test_page_is_one_open_item_naming_containers_and_jobs() -> None:
    store = Store.open(":memory:")
    pager = Pager(store)
    rt = Runtime([Unowned("a", "ida", "vi-0001"), Unowned("b", "idb", "")])
    assert reap_and_page(rt, store, pager) == 2
    reap_and_page(rt, store, pager)  # a second start while it is open: no second page
    (item,) = store.list_inbox("open")
    assert pager.calls == 1 and rt.reaped == 2
    assert item.body["kind"] == "unowned_containers"
    assert item.body["containers"] == [
        {"name": "a", "job": "vi-0001"},
        {"name": "b", "job": ""},
    ]


def test_page_none_when_nothing_unowned() -> None:
    store = Store.open(":memory:")
    pager = Pager(store)
    reap_and_page(Runtime([]), store, pager)
    assert pager.calls == 0 and store.list_inbox("open") == []

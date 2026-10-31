"""The shared unowned selector (#166): `find_unowned` lists vigil-labelled containers
no vigild claims; the startup reap pages them once and removes nothing more."""

from __future__ import annotations

import logging
from typing import Any

import pytest

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
    is_unowned,
)
from vigild.server import reap_and_page


class Box:
    def __init__(self, name: str, labels: dict[str, str], log: list[str]) -> None:
        self.name, self.id, self.labels, self.log = name, f"id-{name}", labels, log
        self.attrs = {"Labels": labels}

    def remove(self, force: bool = False) -> None:
        self.log.append(f"rm {self.name}")


class Daemon:
    def __init__(self, cfg: Config, nets: bool = False) -> None:
        self.log: list[str] = []
        mine = instance_labels(cfg)
        other = {INSTANCE_LABEL: "someone-else"}
        self.boxes = [
            Box("unowned", {LABEL: "s1", JOB_LABEL: "vi-0001"}, self.log),
            Box("owned", {LABEL: "s2", JOB_LABEL: "vi-0002", **mine}, self.log),
            Box("recorded", {LABEL: "s3", JOB_LABEL: "vi-0003"}, self.log),
            Box("other", {LABEL: "s4", JOB_LABEL: "vi-0004", **other}, self.log),
        ]
        self.nets = [Box("unowned-net", {LABEL: "s5"}, self.log)] if nets else []
        self.containers = _Kind(self, "boxes")
        self.networks = _Kind(self, "nets")


class _Kind:
    def __init__(self, d: Daemon, attr: str) -> None:
        self.d, self.attr = d, attr

    def list(self, **kw: Any) -> list[Box]:
        return [b for b in getattr(self.d, self.attr) if LABEL in b.labels]


def test_selector_finds_only_what_no_vigild_claims(cfg: Config) -> None:
    d = Daemon(cfg, nets=True)
    got = find_unowned(d, {"id-recorded"})
    assert got == [
        Unowned("container", "id-unowned", "unowned", "vi-0001"),
        Unowned("network", "id-unowned-net", "unowned-net", ""),
    ]
    # the instance label alone does not make a pre-label container someone's
    assert [u.name for u in find_unowned(d, set())] == ["recorded", "unowned", "unowned-net"]
    rt = DockerRuntime(cfg, d, recorded=lambda job: {"id-recorded"})
    assert rt.unowned() == got
    mine = instance_labels(cfg)
    flags = {b.name: is_unowned(b.labels, b.id, {"id-recorded"}) for b in d.boxes}
    assert flags == {"unowned": True, "owned": False, "recorded": False, "other": False}
    assert not is_unowned({}, "x", set())  # no session label: not a vigil object
    assert not is_unowned({LABEL: "s", **mine}, "x", set())


def test_page_removes_only_ours_and_files_one_item(
    cfg: Config, caplog: pytest.LogCaptureFixture
) -> None:
    store = Store.open(":memory:")
    d = Daemon(cfg)
    rt = DockerRuntime(cfg, d, recorded=lambda job: {"id-recorded"})
    with caplog.at_level(logging.INFO, logger="vigild"):
        assert reap_and_page(rt, store) == 2
    assert sorted(d.log) == ["rm owned", "rm recorded"]  # never unowned, never other
    assert "1 unowned" in caplog.text
    reap_and_page(rt, store)  # a second start while it is open: no second page
    (item,) = store.list_inbox("open")
    assert item.kind == "unowned_containers" and item.body["kind"] == "unowned_containers"
    assert item.body["actions"] == ["dismiss"]
    assert item.body["containers"] == [{"kind": "container", "name": "unowned", "job": "vi-0001"}]


def test_page_none_when_nothing_unowned(cfg: Config) -> None:
    store = Store.open(":memory:")
    d = Daemon(cfg)
    d.boxes = [b for b in d.boxes if b.name != "unowned"]
    rt = DockerRuntime(cfg, d, recorded=lambda job: {"id-recorded"})
    reap_and_page(rt, store)
    assert store.list_inbox("open") == []


def test_page_survives_a_listing_error() -> None:
    class RT:
        def reap(self) -> int:
            return 3

        def unowned(self) -> list[Unowned]:
            raise OSError("daemon gone")

    store = Store.open(":memory:")
    assert reap_and_page(RT(), store) == 3
    assert store.list_inbox("open") == []

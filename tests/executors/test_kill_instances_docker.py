"""Two vigilds on one Docker daemon (pytest -m docker): job ids are per-database counters,
so a production vigild and a scratch one both have a job with the same id. Killing it in
one never touches the other's containers (#162). The job id here is made up for the test
and shared by both, which is the point; only containers this test creates are touched."""

from __future__ import annotations

import contextlib
import secrets
from pathlib import Path
from typing import Any

import pytest

from vigild.config import Config
from vigild.executors.runtime import JOB_LABEL, LABEL, DockerRuntime, instance_labels

pytestmark = pytest.mark.docker


def test_killing_a_job_id_in_one_data_dir_leaves_the_others_containers_running(
    cfg: Config, tmp_path: Path
) -> None:
    cfg2 = cfg.model_copy(deep=True)
    cfg2.vigild.data_dir = str(tmp_path / "second-data")
    a, b = DockerRuntime(cfg), DockerRuntime(cfg2)
    client = a.client
    job = f"vi-killtest-{secrets.token_hex(4)}"  # the same id in both data dirs
    image = cfg.vigild.images.claude_executor
    made: list[Any] = []

    def start(c: Config, name: str) -> Any:
        box = client.containers.run(
            image,
            entrypoint=["sleep", "600"],
            detach=True,
            name=f"{name}-{job}",
            labels={LABEL: f"s-{name}-{job}", JOB_LABEL: job, **instance_labels(c)},
        )
        made.append(box)
        return box

    try:
        a1, a2, b1, b2 = start(cfg, "a1"), start(cfg, "a2"), start(cfg2, "b1"), start(cfg2, "b2")
        assert instance_labels(cfg) != instance_labels(cfg2)
        assert a.stop_job(job, []) == 2
        out = a.purge_job(job, [])
        assert out["containers"] == 2 and out["failed"] == [] and out["unowned"] == []
        gone = {c.name for c in client.containers.list(all=True)}
        assert a1.name not in gone and a2.name not in gone
        for survivor in (b1, b2):
            survivor.reload()
            assert survivor.status == "running", "the other vigild's container was touched"
        assert b.stop_job(job, []) == 2
        assert b.purge_job(job, [])["containers"] == 2
    finally:
        for box in made:
            with contextlib.suppress(Exception):  # already removed by the kill
                box.remove(force=True)

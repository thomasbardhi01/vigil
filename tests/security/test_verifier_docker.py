"""The verifier's container, for real (pytest -m docker): no network, a
read-only checkout copied into the container's tmpfs, the agent uid with no
capabilities, output capped, a timeout that kills."""

from __future__ import annotations

from pathlib import Path

import pytest

from vigild.config import Config
from vigild.executors.runtime import DockerTestRunner
from vigild.verifier import outcome

pytestmark = pytest.mark.docker


@pytest.fixture
def runner(cfg: Config, runtime: object) -> DockerTestRunner:  # runtime: images are built
    return DockerTestRunner(cfg, runtime.client)  # type: ignore[attr-defined]


@pytest.fixture
def source(tmp_path: Path) -> Path:
    src = tmp_path / "verify" / "fx-0001-w1-after" / "src"
    src.mkdir(parents=True)
    (src / "ok.txt").write_text("ok\n")
    return src


def _run(runner: DockerTestRunner, cfg: Config, source: Path, cmd: str, **kw: int):  # type: ignore[no-untyped-def]
    return runner.run(
        cfg.vigild.images.claude_executor,
        source,
        cmd,
        timeout_s=kw.get("timeout_s", 60),
        max_output=kw.get("max_output", 64 << 10),
    )


def test_no_network_read_only_source_agent_uid(
    runner: DockerTestRunner, cfg: Config, source: Path
) -> None:
    r = _run(
        runner,
        cfg,
        source,
        "id -u; grep CapEff /proc/self/status; pwd; cat ok.txt; "
        "touch /src/x 2>/dev/null; echo SRC=$?; touch /work/x; echo WORK=$?; "
        "touch /tmp/x; echo TMP=$?; touch /etc/x 2>/dev/null; echo ROOTFS=$?; "
        'python -c "import urllib.request as u\n'
        "try:\n u.urlopen('https://pypi.org/simple/', timeout=5); print('REACHED')\n"
        "except Exception as e:\n print('BLOCKED', type(e).__name__)\"; exit 3",
    )
    assert r.exit == 3 and outcome(r.exit, r.timed_out) == "fail"
    lines = r.output.splitlines()
    assert lines[0] == "10001", r.output
    assert "CapEff:\t0000000000000000" in r.output
    # the checkout is read-only; the suite runs on a copy in the container's tmpfs
    assert "/work" in lines and "ok" in lines
    assert "SRC=1" in r.output and "WORK=0" in r.output and "TMP=0" in r.output
    assert "ROOTFS=1" in r.output
    assert not (source / "x").exists()
    assert "BLOCKED" in r.output and "REACHED" not in r.output


def test_output_is_capped_to_its_tail(runner: DockerTestRunner, cfg: Config, source: Path) -> None:
    r = _run(
        runner, cfg, source, "head -c 300000 /dev/zero | tr '\\0' a; echo END", max_output=4096
    )
    assert r.exit == 0 and r.truncated
    assert len(r.output) <= 4096 and r.output.rstrip().endswith("END")


def test_a_hung_test_is_killed(runner: DockerTestRunner, cfg: Config, source: Path) -> None:
    r = _run(runner, cfg, source, "sleep 60", timeout_s=3)
    assert r.timed_out and outcome(r.exit, r.timed_out) == "timeout"

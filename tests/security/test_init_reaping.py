"""tini is PID 1 in a session container and reaps orphans (#112). The probe's
root shell stands in for the harness, as tini's child, exactly as in a real
session. Docker tests; they fail on a container whose PID 1 is the harness,
which never reaps."""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable

import pytest

from vigild.executors.base import SessionSpec
from vigild.executors.runtime import DockerRuntime

pytestmark = pytest.mark.docker

# The harness is Python, which waits for its one child and reaps nothing else;
# the probe's default stand-in, dash, reaps every orphan it sees, which would
# hide the bug. So these tests run the agent under a Python parent, as root.
HARNESS = (
    "import subprocess,sys;"
    "sys.exit(subprocess.run(['setpriv','--reuid=10001','--regid=10001','--clear-groups',"
    "'--inh-caps=-all','--','sh','-c',sys.argv[1]]).returncode)"
)


@pytest.fixture(autouse=True)
def python_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "vigild.executors.runtime.as_agent",
        lambda cfg, command: (
            f"exec /opt/vigil-venv/bin/python -c {shlex.quote(HARNESS)} {shlex.quote(command)}"
        ),
    )


ZOMBIES = (
    "z=0; for s in /proc/[0-9]*/stat; do "
    "case \"$(cat $s 2>/dev/null)\" in *') Z '*) z=$((z+1));; esac; done; echo ZOMBIES=$z"
)


def test_orphans_past_the_pids_limit_are_reaped(
    runtime: DockerRuntime, make_spec: Callable[..., SessionSpec]
) -> None:
    limit = runtime.cfg.vigild.container.pids_limit
    _, out = runtime.probe(
        make_spec(),
        f"i=0; while [ $i -lt {limit + 100} ]; do (true &); i=$((i+1)); done; sleep 1; "
        f"{ZOMBIES}; (true) && echo FORK=ok",
    )
    assert "ZOMBIES=0" in out and "FORK=ok" in out, out


def test_a_parallel_test_run_stays_under_the_pids_limit(
    runtime: DockerRuntime, make_spec: Callable[..., SessionSpec]
) -> None:
    """Stand-in for `pytest -n auto`: one worker per CPU, each spawning git
    processes that end up orphaned. Records the peak pids.current."""
    worker = "j=0; while [ $j -lt 150 ]; do (git --version >/dev/null 2>&1 &); j=$((j+1)); done"
    _, out = runtime.probe(
        make_spec(),
        "n=$(nproc); rm -f /tmp/done /tmp/samples; "
        "(while [ ! -e /tmp/done ]; do cat /sys/fs/cgroup/pids.current >> /tmp/samples; "
        "sleep 0.02; done) & "
        f'k=0; wp=""; while [ $k -lt "$n" ]; do ({worker}) & wp="$wp $!"; k=$((k+1)); done; '
        "wait $wp; touch /tmp/done; sleep 1; "
        "echo PEAK=$(sort -n /tmp/samples | tail -1) MAX=$(cat /sys/fs/cgroup/pids.max); "
        + ZOMBIES,
        timeout=300,
    )
    m = re.search(r"PEAK=(\d+) MAX=(\d+)", out)
    assert m, out
    print(f"peak pids.current={m[1]} of pids.max={m[2]}")
    assert int(m[1]) < int(m[2]) and "temporarily unavailable" not in out, out
    assert "ZOMBIES=0" in out, out

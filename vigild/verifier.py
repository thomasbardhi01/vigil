"""The verifier: the only source of test results (owner direction, review round 2).

After a worker exits and its branch is in the vault, vigild runs the task's
`test_cmd` itself, never trusting anything the worker's container wrote:

- **after:** the head commit, taken from the vault (not the worker's clone),
  checked out fresh into a directory vigild owns, with a new `.git` whose
  `core.hooksPath` is /dev/null.
- **before** (when `must_fail_first`): the base commit with the worker's new
  and changed test files (paths `acceptance.TEST_FILE` matches, taken from the
  head) laid over it, so a new test exists but the code it tests doesn't.
  Deleted test files aren't restored; `weakened_tests` rejects those anyway.

Each run gets its own checkout and its own container from the repo's pinned
dev image: no network, read-only root and source, no capabilities, the agent
uid, a pids and memory limit. vigild reads the container's output stream
itself, capped in size and time (`TestRunner`); nothing is read back from a
path. The checkout is removed after the run.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from vigild.workspace import Workspace

VERIFY_SECONDS = 15 * 60
MAX_OUTPUT = 256 << 10  # read at most this much of a run's output
TAIL = 2000  # keep this much in the record


@dataclass(frozen=True)
class RunResult:
    exit: int | None
    output: str
    timed_out: bool = False
    truncated: bool = False


class TestRunner(Protocol):
    def run(
        self, image: str, source: Path, command: str, *, timeout_s: int, max_output: int
    ) -> RunResult: ...


def outcome(code: int | None, timed_out: bool) -> str:
    if timed_out:
        return "timeout"
    if code == 0:
        return "pass"
    if code in (126, 127):
        return "unknown"  # couldn't run in this image
    return "fail"


class Verifier:
    def __init__(
        self, workspace: Workspace, runner: TestRunner, timeout_s: int = VERIFY_SECONDS
    ) -> None:
        self.ws = workspace
        self.runner = runner
        self.timeout_s = timeout_s

    def verify(
        self,
        *,
        repo: str,
        image: str,
        task_id: str,
        base_sha: str,
        head: str,
        test_cmd: str,
        must_fail_first: bool,
    ) -> dict[str, Any]:
        record: dict[str, Any] = {"test_cmd": test_cmd}
        if must_fail_first:
            from vigild.jobs.acceptance import TEST_FILE

            applied = [
                path
                for status, path in self.ws.changed(repo, base_sha, head)
                if status[:1] in ("A", "M") and TEST_FILE.search(path)
            ]
            record["before"] = self._run(
                repo, image, f"{task_id}-before", base_sha, test_cmd, head, applied
            )
        record["after"] = self._run(repo, image, f"{task_id}-after", head, test_cmd, None, [])
        record["provenance"] = "human"  # observed by vigild, not reported by the model
        record["source"] = "verifier"
        return record

    def _run(
        self,
        repo: str,
        image: str,
        name: str,
        sha: str,
        test_cmd: str,
        overlay_from: str | None,
        paths: list[str],
    ) -> dict[str, Any]:
        src = self.ws.verify_checkout(repo, name, sha, overlay_from=overlay_from, paths=paths)
        try:
            r = self.runner.run(
                image, src, test_cmd, timeout_s=self.timeout_s, max_output=MAX_OUTPUT
            )
        finally:
            shutil.rmtree(src.parent, ignore_errors=True)
        out: dict[str, Any] = {
            "sha": sha,
            "exit": r.exit,
            "outcome": outcome(r.exit, r.timed_out),
            "tail": r.output[-TAIL:],
        }
        if overlay_from is not None:
            out["applied"] = paths
        if r.truncated:
            out["truncated"] = True
        return out

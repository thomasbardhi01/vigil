"""Stage 3 acceptance (design "Job execution protocol"), checked by vigild on
the host after the worker container exits and before anything is pushed:
must_fail_first observed, test_cmd passes, files changed inside scope, no test
weakened, cost under the limit. Lint and types run in CI (stage 4)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from vigild.contract.models import TestOutcome, WorkerReport
from vigild.github.publish import out_of_scope

TEST_FILE = re.compile(r"(^|/)(tests?/|test_[^/]*$|[^/]*_test\.[a-z]+$|[^/]*\.test\.[a-z]+$)")
ASSERT = re.compile(r"\b(assert|expect|should|XCTAssert)")


def _git(clone: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=clone, capture_output=True, text=True, check=True
    ).stdout


def weakened_tests(clone: Path, base: str) -> list[str]:
    """Test files deleted, or with fewer assertions than before."""
    out: list[str] = []
    for line in _git(clone, "diff", "--name-status", f"origin/{base}...HEAD").splitlines():
        status, _, path = line.partition("\t")
        if not TEST_FILE.search(path):
            continue
        if status.startswith("D"):
            out.append(f"{path} was deleted")
            continue
        diff = _git(clone, "diff", f"origin/{base}...HEAD", "--", path)
        removed = sum(1 for d in diff.splitlines() if d.startswith("-") and ASSERT.search(d))
        added = sum(1 for d in diff.splitlines() if d.startswith("+") and ASSERT.search(d))
        if removed > added:
            out.append(f"{path} lost {removed - added} assertion(s)")
    return out


def check_worker(
    clone: Path,
    base: str,
    contract: dict[str, Any],
    report: WorkerReport,
    harness: dict[str, Any],
    *,
    cost: float,
) -> list[str]:
    spec = contract["spec"]
    errors: list[str] = []
    if report.task_id != contract["task_id"]:
        errors.append(f"report task_id {report.task_id} is not {contract['task_id']}")
    before = (harness.get("before") or {}).get("outcome")
    after = (harness.get("after") or {}).get("outcome")
    if spec.get("must_fail_first", True):
        if report.test_before is not TestOutcome.FAIL:
            errors.append("must_fail_first: the report says the test did not fail first")
        if before == "pass":
            errors.append("must_fail_first: the harness saw the test pass before the change")
    if report.test_after is not TestOutcome.PASS:
        errors.append("the report says test_cmd does not pass")
    if after is not None and after != "pass" and after != "unknown":
        errors.append(f"test_cmd must pass; the harness saw it {after} after the change")
    changed = [
        f for f in _git(clone, "diff", "--name-only", f"origin/{base}...HEAD").splitlines() if f
    ]
    outside = out_of_scope(changed, spec.get("files_in_scope") or [])
    if outside:
        errors.append(f"files changed outside scope: {outside}")
    for w in weakened_tests(clone, base):
        errors.append(f"test weakened: {w}")
    limit = float((contract.get("limits") or {}).get("max_cost_usd") or 0)
    if limit and cost > limit + 1e-9:
        errors.append(f"cost ${cost:.4f} is over the limit ${limit:.2f}")
    return errors

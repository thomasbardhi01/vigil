"""Stage 3 acceptance (design "Job execution protocol"), checked by vigild on
the host, in the vault, after the worker container exits and before anything
is pushed: must_fail_first observed, test_cmd passes, files changed inside
scope, no test weakened, cost under the limit. Lint and types run in CI.

It fails closed (review round 1, blocker 4): when a task has a `test_cmd`,
the harness record is required, and its before/after outcomes must be
`fail`/`pass` as observed by the harness. A missing record, or an `unknown`
outcome (the command couldn't run in the dev image), is a rejection, never
the worker's word."""

from __future__ import annotations

import re
from typing import Any

from vigild.contract.models import TestOutcome, WorkerReport
from vigild.github.publish import out_of_scope
from vigild.workspace import Workspace

TEST_FILE = re.compile(r"(^|/)(tests?/|test_[^/]*$|[^/]*_test\.[a-z]+$|[^/]*\.test\.[a-z]+$)")
ASSERT = re.compile(r"\b(assert|expect|should|XCTAssert)")


def weakened_tests(ws: Workspace, repo: str, base_sha: str, head: str) -> list[str]:
    """Test files deleted (renames count as deletes), or with fewer assertions."""
    out: list[str] = []
    for status, path in ws.changed(repo, base_sha, head):
        if not TEST_FILE.search(path):
            continue
        if status.startswith("D"):
            out.append(f"{path} was deleted")
            continue
        diff = ws.diff(repo, base_sha, head, path)
        removed = sum(1 for d in diff.splitlines() if d.startswith("-") and ASSERT.search(d))
        added = sum(1 for d in diff.splitlines() if d.startswith("+") and ASSERT.search(d))
        if removed > added:
            out.append(f"{path} lost {removed - added} assertion(s)")
    return out


def check_harness(spec: dict[str, Any], harness: dict[str, Any] | None) -> list[str]:
    if not spec.get("test_cmd"):
        return []
    if not harness:
        return ["the harness record is missing: test_cmd was not observed, so nothing is accepted"]
    errors: list[str] = []
    before = (harness.get("before") or {}).get("outcome")
    after = (harness.get("after") or {}).get("outcome")
    if spec.get("must_fail_first", True) and before != "fail":
        errors.append(f"must_fail_first: the harness saw the test {before or 'not run'} before")
    if after != "pass":
        errors.append(f"test_cmd must pass; the harness saw it {after or 'not run'} after")
    return errors


def check_worker(
    ws: Workspace,
    repo: str,
    base_sha: str,
    head: str,
    contract: dict[str, Any],
    report: WorkerReport,
    harness: dict[str, Any] | None,
    *,
    cost: float,
) -> list[str]:
    spec = contract["spec"]
    errors: list[str] = []
    if report.task_id != contract["task_id"]:
        errors.append(f"report task_id {report.task_id} is not {contract['task_id']}")
    if spec.get("must_fail_first", True) and report.test_before is not TestOutcome.FAIL:
        errors.append("must_fail_first: the report says the test did not fail first")
    if report.test_after is not TestOutcome.PASS:
        errors.append("the report says test_cmd does not pass")
    errors += check_harness(spec, harness)
    changed = [path for _, path in ws.changed(repo, base_sha, head)]
    outside = out_of_scope(changed, spec.get("files_in_scope") or [])
    if outside:
        errors.append(f"files changed outside scope: {outside}")
    for w in weakened_tests(ws, repo, base_sha, head):
        errors.append(f"test weakened: {w}")
    limit = float((contract.get("limits") or {}).get("max_cost_usd") or 0)
    if limit and cost > limit + 1e-9:
        errors.append(f"cost ${cost:.4f} is over the limit ${limit:.2f}")
    return errors

"""Stage 3 acceptance (design "Job execution protocol"), checked by vigild on
the host, in the vault, after the worker container exits and before anything
is pushed: must_fail_first observed, test_cmd passes, files changed inside
scope, no test weakened, cost under the limit. Lint and types run in CI.

Test results come only from vigild's verifier (owner direction, review round
2; `vigild/verifier.py`): the worker report's test fields are ignored. It
fails closed: a task with no test_cmd, a missing verifier record, or any
outcome other than `fail` before and `pass` after is a rejection."""

from __future__ import annotations

import re
from typing import Any

from vigild.contract.models import WorkerReport
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


def check_tests(spec: dict[str, Any], tests: dict[str, Any] | None) -> list[str]:
    if not str(spec.get("test_cmd") or "").strip():
        return ["the contract has no test_cmd, so nothing can be accepted"]
    if not tests or tests.get("source") != "verifier":
        return ["the verifier's record is missing: test_cmd was not observed, so nothing is accepted"]
    errors: list[str] = []
    before = (tests.get("before") or {}).get("outcome")
    after = (tests.get("after") or {}).get("outcome")
    if spec.get("must_fail_first", True) and before != "fail":
        errors.append(f"must_fail_first: the verifier saw the test {before or 'not run'} before")
    if after != "pass":
        errors.append(f"test_cmd must pass; the verifier saw it {after or 'not run'} after")
    return errors


def check_worker(
    ws: Workspace,
    repo: str,
    base_sha: str,
    head: str,
    contract: dict[str, Any],
    report: WorkerReport,
    tests: dict[str, Any] | None,
    *,
    cost: float,
) -> list[str]:
    spec = contract["spec"]
    errors: list[str] = []
    if report.task_id != contract["task_id"]:
        errors.append(f"report task_id {report.task_id} is not {contract['task_id']}")
    errors += check_tests(spec, tests)
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

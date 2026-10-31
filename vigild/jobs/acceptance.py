"""Stage 3 acceptance (design "Job execution protocol"), checked by vigild on
the host, in the vault, after the worker container exits and before anything
is pushed: must_fail_first observed, test_cmd passes, files changed inside
scope, no test weakened, the completion-integrity rules
(`jobs/integrity.py`), cost under the limit. Lint and types run in CI.

Test results come only from vigild's verifier (owner direction, review round
2; `vigild/verifier.py`): the worker report's test fields are ignored. It
fails closed: a task with no test_cmd, a missing verifier record, or any
outcome other than `fail` before and `pass` after is a rejection."""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable, Sequence
from typing import Any

from vigild.contract.models import WorkerReport
from vigild.github.publish import artifact_paths, out_of_scope
from vigild.intake.paths import in_scope
from vigild.intake.spec_gate import test_cmd_problem
from vigild.jobs.artifacts import ac_refs, parse_spec
from vigild.jobs.integrity import Finding, blocking, check_integrity
from vigild.verifier import TEST_FILE, ReadFile, invoked_scripts, runner_class
from vigild.workspace import Workspace

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


NO_HIDDEN = "runner file task: no hidden tests, so it cannot pass"


def escalates(tests: dict[str, Any] | None) -> bool:
    """A runner-file task whose hidden tests don't exist: it is built and
    reported, never accepted; the owner decides (owner ruling, 2026-10-23)."""
    if not tests or not tests.get("runner_files") or tests.get("hidden_disabled"):
        return False
    return not (tests.get("hidden") or {}).get("files")


def hidden_errors(tests: dict[str, Any]) -> list[str]:
    """For a task whose scope names a runner file, the hidden tests decide:
    they failed on the base, pass on the head, head ran no fewer. The messages
    carry counts and reasons, never a test's name or output: they reach the
    owner's page and a re-plan's context."""
    if not tests.get("runner_files") or tests.get("hidden_disabled"):
        return []
    hidden = tests.get("hidden") or {}
    if escalates(tests):
        return [f"{NO_HIDDEN}: {hidden.get('reason') or 'none were written'}"]
    errors: list[str] = []
    if hidden.get("tampered"):
        errors.append("the branch has files in the hidden directory; hidden tests didn't run")
    elif not hidden.get("failed_on_base"):
        errors.append("hidden tests must fail on the base; they didn't")
    if not hidden.get("tampered") and not hidden.get("passed_on_head"):
        errors.append("hidden tests must pass on the head; they didn't")
    ran = hidden.get("ran") or {}
    if ran.get("checked") and not ran.get("ok"):
        errors.append("head ran less than base in the hidden tests' own run")
    return errors


def ac_plan(
    spec_md: str, read: ReadFile | None = None, only: Collection[str] | None = None
) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """(runs, refusals) for the approved spec.md's AC test commands (#136). `runs` is
    (command, AC ids) for each distinct command, in first-seen order; never the
    worker's. A command the spec gate refuses now (a spec approved before a gate rule)
    is never skipped: it is a refusal that fails the task, naming the AC and why.
    `only` limits it to those AC ids (a worker of several answers for the ACs it
    names, and for those no worker names)."""
    found: dict[str, list[str]] = {}
    refused: list[str] = []
    for c in parse_spec(spec_md).criteria:
        cmd = (c.test_cmd or "").strip()
        if only is not None and c.ident not in only:
            continue
        if not cmd:
            continue
        why = test_cmd_problem(cmd, read)
        if why is None:
            found.setdefault(cmd, []).append(c.ident)
        else:
            refused.append(f"{c.ident}: `{cmd}` is not a runnable test command ({why})")
    return list(found.items()), refused


def ac_commands(
    spec_md: str, read: ReadFile | None = None, only: Collection[str] | None = None
) -> list[tuple[str, list[str]]]:
    """The runnable part of `ac_plan`."""
    return ac_plan(spec_md, read, only)[0]


def plan_runner_class(
    spec_md: str,
    workers: Sequence[Any],
    runner_config: Sequence[str],
    read: ReadFile | None = None,
) -> dict[str, list[str]]:
    """Each plan worker's runner files (#142), from the approved spec's AC commands as
    the verifier reads them: the same parser, the same per-worker AC split, and (#144)
    the same reader, the base's files, so a command verify refuses is dropped here too."""
    idents = [c.ident for c in parse_spec(spec_md).criteria]
    texts = [f"{w.why or ''} {w.done_when or ''}" for w in workers]
    out: dict[str, list[str]] = {}
    for w, mine in zip(workers, texts, strict=True):
        cmds = [c for c, _ in ac_commands(spec_md, read, worker_acs(idents, texts, mine))]
        out[w.task_id] = runner_class(w.files_in_scope, runner_config, w.test_cmd, cmds)
    return out


def live_workers(tasks: Iterable[Any]) -> list[Any]:
    """The job's tasks that still answer for its ACs: not re-planned away or
    abandoned, and not a dependency job (#136)."""
    return [
        t
        for t in tasks
        if t.state not in ("superseded", "abandoned") and t.contract.get("shape") != "deps"
    ]


def kept_workers(tasks: Iterable[Any], planned: Collection[str]) -> list[Any]:
    """The live tasks a re-plan keeps: live (see `live_workers`), already built from a
    plan (not `submitted`/`awaiting_approval`) and not named again in the new plan."""
    waiting = ("submitted", "awaiting_approval")
    return [t for t in live_workers(tasks) if t.state not in waiting and t.id not in planned]


def contract_text(contract: dict[str, Any]) -> str:
    """What a worker contract says about its ACs: `why` and `done_when`."""
    return f"{contract.get('why') or ''} {(contract.get('spec') or {}).get('done_when') or ''}"


def worker_acs(idents: Iterable[str], live_texts: Sequence[str], mine: str) -> set[str] | None:
    """The AC ids one worker's after run answers for (#136), or None for all. A
    one-worker job answers for every AC. With several, a worker answers for the ACs
    its own text names, and for those no live worker names (the fail-safe for a job
    approved before the spec gate checked that), since no branch is better placed."""
    if len(live_texts) <= 1:
        return None
    named: set[str] = set()
    for t in live_texts:
        named |= ac_refs(t)
    return ac_refs(mine) | (set(idents) - named)


def ac_errors(tests: dict[str, Any]) -> list[str]:
    """A stage-3 error for each AC command that selected no test or didn't pass."""
    errors: list[str] = [str(e) for e in tests.get("ac_refused") or []]
    for run in tests.get("ac") or []:
        who = "/".join(run.get("acs") or []) or "AC"
        cmd = run.get("command")
        if run.get("outcome") == "timeout":
            errors.append(f"{who}: `{cmd}` timed out (no report)")
        elif not run.get("selected") or not run.get("report"):
            errors.append(f"{who}: `{cmd}` selected 0 tests")
        elif run.get("outcome") != "pass":
            errors.append(f"{who}: `{cmd}` did not pass (the verifier saw {run.get('outcome')})")
    return errors


def check_tests(spec: dict[str, Any], tests: dict[str, Any] | None) -> list[str]:
    if not str(spec.get("test_cmd") or "").strip():
        return ["the contract has no test_cmd, so nothing can be accepted"]
    if not tests or tests.get("source") != "verifier":
        return [
            "the verifier's record is missing: test_cmd was not observed, so nothing is accepted"
        ]
    errors: list[str] = []
    before = (tests.get("before") or {}).get("outcome")
    after = (tests.get("after") or {}).get("outcome")
    if spec.get("must_fail_first", True) and before != "fail":
        errors.append(f"must_fail_first: the verifier saw the test {before or 'not run'} before")
    if after != "pass":
        errors.append(f"test_cmd must pass; the verifier saw it {after or 'not run'} after")
    ids = tests.get("ids") or {}
    if spec.get("must_fail_first", True) and ids.get("checked"):
        # round 3, F3: the failure "before" must be the worker's own test failing
        if not ids.get("failing_before"):
            errors.append(
                "must_fail_first: none of the worker's new or changed tests failed before; "
                "the failure was elsewhere in test_cmd"
            )
        if ids.get("not_passing_after"):
            still = ids["not_passing_after"]
            errors.append(f"the worker's tests that failed before don't pass after: {still}")
    if not spec.get("must_fail_first", True):
        # #31 item 1: tests-only tasks still have to bring tests, and they must run and pass
        if not ids.get("checked"):
            errors.append(
                "must_fail_first is off: that the worker's own tests ran can't be confirmed "
                f"({ids.get('note') or 'the runner gave no report'})"
            )
        else:
            if not ids.get("worker_ran"):
                errors.append(
                    "must_fail_first is off, so at least one new test id (absent from the "
                    "base runs) in the worker's test files must run and pass; none of the worker's "
                    "new tests ran (zero "
                    "collected; skipped, xfail and todo don't count, and an edited test that "
                    "keeps its id isn't new)"
                )
            if ids.get("not_passing_after"):
                errors.append(f"the worker's tests don't pass: {ids['not_passing_after']}")
    ran = tests.get("ran") or {}
    if ran.get("unknown"):
        errors.append(f"what ran can't be compared: {ran.get('note')}")
    if ran.get("checked") and not ran.get("ok"):
        # owner direction, round 3: head may add tests, never run fewer or skip more
        errors.append(
            "head ran less than base: "
            f"missing ids {ran.get('missing_ids')}, missing files {ran.get('missing_files')}, "
            f"skipped {ran.get('skipped')}, xfail {ran.get('xfail')}"
        )
    return [*errors, *ac_errors(tests), *hidden_errors(tests)]


def runner_config_changes(
    ws: Workspace,
    repo: str,
    base_sha: str,
    head: str,
    contract: dict[str, Any],
    runner_config: list[str] | tuple[str, ...],
    ac_cmds: Iterable[str] = (),
) -> tuple[list[str], list[str]]:
    """(refused, allowed): changed files that decide how tests run (round 3,
    F1). Allowed only when the spec names the exact path, not a glob. The scripts
    an AC command runs count as `test_cmd`'s do (#136)."""
    spec = contract["spec"]
    scripts = [
        s for cmd in [str(spec.get("test_cmd") or ""), *ac_cmds] for s in invoked_scripts(cmd)
    ]
    globs = [*runner_config, *scripts]
    named = set(spec.get("files_in_scope") or [])
    changed = sorted({path for _, path in ws.changed(repo, base_sha, head)})
    hits = [p for p in changed if in_scope(p, globs)]
    return [p for p in hits if p not in named], [p for p in hits if p in named]


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
    runner_config: list[str] | tuple[str, ...] = (),
    session_base: str | None = None,
    on_findings: Callable[[list[Finding]], None] | None = None,
) -> list[str]:
    spec = contract["spec"]
    errors: list[str] = []
    vendored = sorted(
        p for _, p in ws.changed(repo, base_sha, head) if "node_modules" in p.split("/")
    )
    if vendored:
        # round 4, item 5: installed packages are the image's, never the worker's
        errors.append(f"node_modules is never committed: {vendored[:20]}")
    ac_cmds = [str(r.get("command") or "") for r in (tests or {}).get("ac") or []]
    refused, _ = runner_config_changes(ws, repo, base_sha, head, contract, runner_config, ac_cmds)
    if refused:
        errors.append(
            f"changes how tests run: {refused}; the approved spec must name each of these "
            "by its exact path in files in scope"
        )
    if report.task_id != contract["task_id"]:
        errors.append(f"report task_id {report.task_id} is not {contract['task_id']}")
    errors += check_tests(spec, tests)
    if session_base and not ws.is_ancestor(repo, session_base, head):
        # the branch was rewritten (reset, amend, rebase): what vigild committed is gone
        errors.append(
            "vigild's pre-session commit is missing from the branch (history was rewritten); "
            "the files can't be checked against scope"
        )
        return errors
    changed = [path for _, path in ws.changed(repo, session_base or base_sha, head)]
    own = artifact_paths(str(contract.get("job_id") or ""), str(contract.get("task_id") or ""))
    outside = out_of_scope(changed, [*(spec.get("files_in_scope") or []), *own])
    if outside:
        errors.append(f"files changed outside scope: {outside}")
    for w in weakened_tests(ws, repo, base_sha, head):
        errors.append(f"test weakened: {w}")
    # #104: rules only, never fixed; #131: report-only unless integrity.ENFORCE
    found = check_integrity(ws, repo, base_sha, head, report)
    if on_findings and found:
        on_findings(found)
    errors += [str(f) for f in blocking(found)]
    limit = float((contract.get("limits") or {}).get("max_cost_usd") or 0)
    if limit and cost > limit + 1e-9:
        errors.append(f"cost ${cost:.4f} is over the limit ${limit:.2f}")
    return errors

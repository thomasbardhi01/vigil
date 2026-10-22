"""The spec gate.

Per task: a task without `test_cmd` and `done_when` does not run; it becomes
a spec-writing job (routing rule 1).

Per job (stage 1 acceptance): spec.md has every section, every acceptance
criterion has a test command, every worker contract in plan.md validates,
worker scopes sit inside the spec's scope, dependencies name real workers,
and the money paths the spec flags are exactly the ones the path rules find.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from vigild.contract.models import BUILT_VERIFY_LEVELS, Task, WorkerContract
from vigild.intake.paths import matches, matches_any
from vigild.jobs.artifacts import SPEC_SECTIONS, PlanDoc, SpecDoc


@dataclass(frozen=True)
class GateResult:
    ok: bool
    needs_spec: bool = False
    errors: list[str] = field(default_factory=list)


def check_task(task: Task) -> GateResult:
    errors = [
        f"{key} is required before a task can run"
        for key in ("test_cmd", "done_when")
        if not (getattr(task.spec, key) or "").strip()
    ]
    return GateResult(ok=not errors, needs_spec=bool(errors), errors=errors)


def _in_scope(path: str, scope: Sequence[str]) -> bool:
    return any(path == s or matches(path, s) for s in scope)


def _overlap(a: str, b: str) -> bool:
    return a == b or matches(a, b) or matches(b, a)


def _ordered(workers: list[WorkerContract]) -> set[tuple[str, str]]:
    """Pairs (x, y) where y runs after x, through any chain of depends_on."""
    deps = {w.task_id: set(w.depends_on) for w in workers}
    after: set[tuple[str, str]] = set()
    for w in workers:
        stack, seen = list(deps[w.task_id]), set()
        while stack:
            d = stack.pop()
            if d in seen or d not in deps:
                continue
            seen.add(d)
            after.add((d, w.task_id))
            stack.extend(deps[d])
    return after


def parallel_pairs(workers: list[WorkerContract]) -> list[tuple[WorkerContract, WorkerContract]]:
    order = _ordered(workers)
    return [
        (a, b)
        for i, a in enumerate(workers)
        for b in workers[i + 1 :]
        if (a.task_id, b.task_id) not in order and (b.task_id, a.task_id) not in order
    ]


def check_job_spec(spec: SpecDoc, plan: PlanDoc, money_globs: Sequence[str]) -> list[str]:
    errors: list[str] = []
    for sec in SPEC_SECTIONS:
        if sec not in spec.sections:
            errors.append(f"spec.md is missing the '## {sec}' section")
    if not spec.criteria:
        errors.append("spec.md has no acceptance criteria")
    for c in spec.criteria:
        if not c.test_cmd:
            errors.append(f"spec.md {c.ident} has no test command (`test: \\`cmd\\``)")

    errors.extend(plan.errors)
    if not plan.workers and not plan.errors:
        errors.append("plan.md has no worker contracts")
    ids = [w.task_id for w in plan.workers]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"plan.md repeats worker {dup}")
    for w in plan.workers:
        for dep in w.depends_on:
            if dep not in ids:
                errors.append(f"worker {w.task_id} depends on unknown worker {dep}")
        for f in w.files_in_scope:
            if not _in_scope(f, spec.files_in_scope):
                errors.append(f"worker {w.task_id} scope {f} is outside spec.md's files in scope")

    # Single writer by default; parallel writers only with disjoint files and
    # interfaces pinned in spec.md (owner decisions 2026-10-22).
    pairs = parallel_pairs(plan.workers)
    for a, b in pairs:
        shared = sorted({f for f in a.files_in_scope for g in b.files_in_scope if _overlap(f, g)})
        if shared:
            errors.append(
                f"workers {a.task_id} and {b.task_id} run in parallel but their files are not "
                f"disjoint: {shared}; order them with depends_on or split the files"
            )
    if pairs and not spec.interfaces:
        errors.append("parallel workers need their shared interfaces pinned in '## Interfaces'")

    # The verification ladder: every criterion's level, and why not higher at 0.
    levels = {v.criterion: v for v in plan.verify}
    for c in spec.criteria:
        if c.ident not in levels and not plan.errors:
            errors.append(f"plan.md has no verify entry for {c.ident}")
    for v in plan.verify:
        if v.level not in BUILT_VERIFY_LEVELS:
            errors.append(f"{v.criterion}: verify level {v.level} isn't built yet (phase 1: 0)")

    in_scope = set(spec.files_in_scope) | {f for w in plan.workers for f in w.files_in_scope}
    found = {f for f in in_scope if matches_any(f, money_globs)}
    flagged = set(spec.money_paths)
    for f in sorted(found - flagged):
        errors.append(f"{f} is a money/auth/consent path but spec.md does not flag it")
    for f in sorted(flagged - found):
        errors.append(f"spec.md flags {f} as a money path, but the path rules don't match it")
    return errors

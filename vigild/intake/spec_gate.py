"""The spec gate.

Per task: a task without `test_cmd` and `done_when` does not run; it becomes
a spec-writing job (routing rule 1).

Per job (stage 1 acceptance): spec.md has every section, every acceptance
criterion has a test command, every worker contract in plan.md validates,
worker scopes sit inside the spec's scope (strict globs, no `..` or absolute
paths), dependencies name real workers and form no cycle, parallel workers'
scopes are provably disjoint and their interfaces pinned, every test_cmd can
run in the repo's dev image, and the money paths the spec flags are exactly
the ones the path rules find.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from vigild.contract.models import BUILT_VERIFY_LEVELS, Task, WorkerContract
from vigild.intake.paths import globs_overlap, in_scope, matches_any, scope_entry_error
from vigild.jobs.artifacts import SPEC_SECTIONS, PlanDoc, SpecDoc


@dataclass(frozen=True)
class GateResult:
    ok: bool
    needs_spec: bool = False
    errors: list[str] = field(default_factory=list)


LIST_OPS = re.compile(r"(&&|\|\||;|\||\n)")
ALWAYS_ZERO = {"true", ":", "echo", "printf"}


def _words(segment: str) -> list[str]:
    seg = segment.strip().strip("(){} \t")
    try:
        words = shlex.split(seg)
    except ValueError:
        words = seg.split()
    return [w for w in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]


def _always_zero(words: list[str]) -> bool:
    if not words:
        return True
    return words[0] in ALWAYS_ZERO or words == ["exit", "0"]


def bad_test_cmd(cmd: str | None) -> str | None:
    """Why a test_cmd can't be a test, or None (review round 2, N2): it's
    empty, every part of it is a no-op (`true`, `:`, `exit 0`, `echo ...`),
    or it ends in a no-op after `;`, `||` or `|`, so it exits 0 whatever ran
    before. vigild runs test_cmd to decide; one that can't fail decides nothing."""
    if not (cmd or "").strip():
        return "test_cmd is empty"
    assert cmd is not None
    parts = LIST_OPS.split(cmd)
    segments, ops = parts[0::2], parts[1::2]
    words = [_words(seg) for seg in segments]
    if all(_always_zero(w) or w == ["exit"] for w in words):
        return f"test_cmd `{cmd.strip()}` can't fail: it's a no-op"
    # drop empty trailing segments (a trailing `;` or newline)
    while len(words) > 1 and not words[-1]:
        words.pop()
        ops.pop()
    if ops and ops[-1] in (";", "||", "|", "\n") and _always_zero(words[-1]):
        tail = f"{ops[-1].strip() or 'newline'} {' '.join(words[-1])}"
        return f"test_cmd `{cmd.strip()}` always exits 0: it ends in `{tail}`"
    return None


def check_task(task: Task) -> GateResult:
    errors = [
        f"{key} is required before a task can run"
        for key in ("test_cmd", "done_when")
        if not (getattr(task.spec, key) or "").strip()
    ]
    if (task.spec.test_cmd or "").strip() and (why := bad_test_cmd(task.spec.test_cmd)):
        errors.append(why)
    return GateResult(ok=not errors, needs_spec=bool(errors), errors=errors)


TICKED = re.compile(r"`[^`]+`")


def _scope_within(entry: str, spec_scope: Sequence[str]) -> bool:
    """A worker's entry sits inside the spec's scope: a literal path must be in
    scope; a glob must equal a spec entry or be covered by a `**` entry."""
    if entry in spec_scope or (not set("*?[") & set(entry) and in_scope(entry, spec_scope)):
        return True
    return any(s.endswith("/**") and entry.startswith(s[:-2]) for s in spec_scope)


def cycles(workers: list[WorkerContract]) -> list[str]:
    deps = {w.task_id: [d for d in w.depends_on] for w in workers}
    found: list[str] = []
    state: dict[str, int] = {}

    def visit(n: str, path: list[str]) -> None:
        state[n] = 1
        for d in deps.get(n, []):
            if d not in deps:
                continue
            if state.get(d) == 1:
                found.append(
                    " -> ".join([*path[path.index(d) :], d]) if d in path else f"{n} -> {d}"
                )
            elif state.get(d) is None:
                visit(d, [*path, d])
        state[n] = 2

    for n in deps:
        if state.get(n) is None:
            visit(n, [n])
    return found


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


def check_job_spec(
    spec: SpecDoc,
    plan: PlanDoc,
    money_globs: Sequence[str],
    *,
    missing_tools: Callable[[str], list[str]] | None = None,
) -> list[str]:
    errors: list[str] = []
    for entry in spec.files_in_scope:
        if err := scope_entry_error(entry):
            errors.append(f"spec.md files in scope: {err}")
    for sec in SPEC_SECTIONS:
        if sec not in spec.sections:
            errors.append(f"spec.md is missing the '## {sec}' section")
    if not spec.criteria:
        errors.append("spec.md has no acceptance criteria")
    for c in spec.criteria:
        if not c.test_cmd:
            errors.append(f"spec.md {c.ident} has no test command (`test: \\`cmd\\``)")
        elif why := bad_test_cmd(c.test_cmd):
            errors.append(f"spec.md {c.ident}: {why}")

    errors.extend(plan.errors)
    if not plan.workers and not plan.errors:
        errors.append("plan.md has no worker contracts")
    ids = [w.task_id for w in plan.workers]
    for dup in sorted({i for i in ids if ids.count(i) > 1}):
        errors.append(f"plan.md repeats worker {dup}")
    for w in plan.workers:
        if why := bad_test_cmd(w.test_cmd):
            errors.append(f"worker {w.task_id}: {why}")
        for dep in w.depends_on:
            if dep not in ids:
                errors.append(f"worker {w.task_id} depends on unknown worker {dep}")
        for f in w.files_in_scope + w.out_of_scope:
            if err := scope_entry_error(f):
                errors.append(f"worker {w.task_id}: {err}")
        for f in w.files_in_scope:
            if not scope_entry_error(f) and not _scope_within(f, spec.files_in_scope):
                errors.append(f"worker {w.task_id} scope {f} is outside spec.md's files in scope")
        if missing_tools is not None:
            lacking = missing_tools(w.test_cmd)
            if lacking:
                errors.append(
                    f"worker {w.task_id} test_cmd needs {lacking}, which the repo's dev image "
                    "doesn't have; use a check the image can run"
                )
    for loop in cycles(plan.workers):
        errors.append(f"plan.md has a dependency cycle: {loop}")
    for c in spec.criteria:
        if c.test_cmd and missing_tools is not None and missing_tools(c.test_cmd):
            errors.append(
                f"spec.md {c.ident} test needs {missing_tools(c.test_cmd)}, which the repo's "
                "dev image doesn't have"
            )

    # Single writer by default; parallel writers only with disjoint files and
    # interfaces pinned in spec.md (owner decisions 2026-10-22).
    pairs = parallel_pairs(plan.workers)
    for a, b in pairs:
        shared = sorted(
            {
                f"{f} / {g}"
                for f in a.files_in_scope
                for g in b.files_in_scope
                if globs_overlap(f, g)
            }
        )
        if shared:
            errors.append(
                f"workers {a.task_id} and {b.task_id} run in parallel but their files are not "
                f"disjoint: {shared}; order them with depends_on or split the files"
            )
    if pairs and not any(TICKED.search(i) for i in spec.interfaces):
        errors.append(
            "parallel workers need their shared interfaces pinned in '## Interfaces': "
            "name the files, signatures or formats in backticks"
        )

    # The verification ladder: every criterion's level, and why not higher at 0.
    levels = {v.criterion: v for v in plan.verify}
    for c in spec.criteria:
        if c.ident not in levels and not plan.errors:
            errors.append(
                f"plan.md has no verify entry for {c.ident} (verify names "
                f"{sorted(levels) or 'nothing'}; use the spec's ids: AC1, AC2, …)"
            )
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

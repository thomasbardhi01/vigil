"""vigild pre-fills the mechanical parts of the spec (ADR-0005 part 5).

Before the coord runs, vigild works out what it can without a model: the repo
paths the request names (the router's own scope-hint extraction, plus the
issue), which of them are runner files, money paths or pinned paths, the
scope rules as text, and `test_cmd` candidates. The coord gets that as a
fenced `prefill` section in its packet and, on a first draft, as a skeleton
`spec.md` and `plan.md` in its clone with the goal, acceptance criteria and
risks left as `TODO(coord)`. The spec gate is unchanged and checks all of it.

Paths are read from the repo at `base_sha` (the coord's own fresh clone); a
name that is not a file there is dropped with a note."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from vigild.config import RepoPolicy
from vigild.gitsafe import GitError, git
from vigild.intake.paths import in_scope, matches_any, scope_entry_error
from vigild.packets.fence import fence
from vigild.router.rules import request_paths
from vigild.verifier import runner_overlap

TODO = "TODO(coord)"
MAX_CANDIDATES = 40
MAX_TESTS_PER_STEM = 6
MAX_DROPPED = 10
# a bare name with one of these suffixes is a file name; others (`e.g`) are prose
FILE_SUFFIXES = (
    ".py", ".ts", ".tsx", ".js", ".mjs", ".md", ".yaml", ".yml", ".json", ".toml", ".sh", ".sql",
)  # fmt: skip

RULES = (
    "- Exact files or `dir/**`: every entry in `## Files in scope` and in a worker's "
    "`files_in_scope` is one file path or a directory's `dir/**`, never a bare directory "
    "(it matches only itself).\n"
    "- Each worker's `files_in_scope` sits inside spec.md's `## Files in scope`.\n"
    "- A runner file named in scope is named by its exact path (vigild sets the task's "
    "runner-file flag and hidden tests follow); a money path named in scope is listed "
    "under `## Money paths`, and `## Money paths` lists no file the rules don't match."
)
KEEP = (
    "Keep the scope rules and the runner, money and pinned flags. The candidate files are a "
    "starting point: you may narrow or widen them, and each file you add or remove gets a "
    "line in `spec_changelog.md`. You write the goal, the acceptance criteria and the risks."
)


@dataclass
class Prefill:
    candidates: list[str] = field(default_factory=list)
    runner_files: list[str] = field(default_factory=list)
    money_paths: list[str] = field(default_factory=list)
    pinned_paths: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    test_cmds: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    def body(self) -> str:
        def lines(title: str, items: Sequence[str]) -> str:
            return f"{title}:\n" + ("\n".join(f"- {i}" for i in items) or "- (none)")

        parts = [
            lines("Candidate files (they exist at base_sha)", [f"`{c}`" for c in self.candidates]),
            lines("Runner files (the repo's runner_config)", self.runner_files),
            lines("Money paths (guard's rules)", self.money_paths),
            lines("Pinned paths (the repo's ladder_pinned_paths)", self.pinned_paths),
            lines("test_cmd candidates", [f"`{c}`" for c in self.test_cmds]),
            lines("Named as out of scope (by the request)", [f"`{c}`" for c in self.out_of_scope]),
        ]
        if self.dropped:
            parts.append(lines("Dropped", self.dropped))
        return "\n\n".join(parts)

    def section(self, job_id: str, *, skeleton: bool) -> str:
        """The packet's `prefill` part: the rules and the keep-rule as vigild's own
        text, the computed lists (they come from the request's words) fenced."""
        where = (
            f"The skeleton is in `.vigil/{job_id}/spec.md` and `.vigil/{job_id}/plan.md`: "
            f"edit them in place; `{TODO}` marks what is yours to write.\n\n"
            if skeleton
            else ""
        )
        return (
            "vigild computed this before you started.\n\n"
            f"Scope rules (the spec gate enforces them):\n{RULES}\n\n{KEEP}\n\n{where}"
            + fence("prefill", self.body())
        )

    def spec_md(self, title: str = "") -> str:
        head = " ".join(title.split())[:80]
        files = "\n".join(f"- `{c}`" for c in self.candidates) or f"- {TODO}"
        out = "\n".join(f"- `{c}`" for c in self.out_of_scope) or f"- {TODO}"
        money = "\n".join(f"- `{c}`" for c in self.money_paths) or "none"
        return (
            f"# Spec: {head or TODO}\n\n"
            f"## Goal\n{TODO}\n\n"
            f"## Non-goals\n{TODO}\n\n"
            f"## Acceptance criteria\n- AC1: {TODO}\n\n"
            f"## Files in scope\n{files}\n\n"
            f"## Files out of scope\n{out}\n\n"
            f"## Money paths\n{money}\n\n"
            f"## Risks\n{TODO}\n\n"
            f"## Rollback\n{TODO}\n"
        )

    def plan_md(self, job_id: str) -> str:
        worker = {
            "task_id": f"{job_id}-w1",
            "goal": TODO,
            "why": TODO,
            "done_when": TODO,
            "test_cmd": TODO,
            "files_in_scope": self.candidates,
            "out_of_scope": self.out_of_scope,
        }
        cmds = "\n".join(f"- `{c}`" for c in self.test_cmds) or "- (none)"
        return (
            f"## Notes addressed\n{TODO}\n\n"
            f"## Workers\n"
            f"Pick each worker's `test_cmd` from the candidates (or write your own):\n{cmds}\n\n"
            "```json\n" + json.dumps({"workers": [worker], "verify": []}, indent=1) + "\n```\n"
        )


NEGATION = re.compile(r"\b(not|never)\b|out of scope|don.t touch", re.I)
BOUNDARY = re.compile(r"\.(?=\s|$)|;|\n")


def _excluded(text: str, hint: str) -> bool:
    """Every place the text names `hint` is a sentence that rules it out: it starts with
    Not, or says out of scope, not, never or don't touch before the path."""
    seen = []
    start = text.find(hint)
    while start != -1:
        cut = max((m.end() for m in BOUNDARY.finditer(text, 0, start)), default=0)
        seen.append(bool(NEGATION.search(text[cut:start])))
        start = text.find(hint, start + len(hint))
    return bool(seen) and all(seen)


def _files(repo: Path) -> list[str]:
    try:
        out = git(repo, "ls-files", "-z", raw=True)
    except GitError, OSError:
        return []
    return [p for p in out.split("\0") if p]


def _is_file(repo: Path, rel: str) -> bool:
    if scope_entry_error(rel):
        return False
    root = Path(os.path.realpath(repo))
    real = Path(os.path.realpath(repo / rel))
    return root in real.parents and real.is_file()


def _test_patterns(stem: str) -> list[str]:
    return [f"test_{stem}*.py", f"{stem}_test.py", f"{stem}.test.*", f"{stem}.spec.*"]


def _is_test_file(name: str) -> bool:
    return bool(re.match(r"(test_.*\.py|.*_test\.py|.*\.(test|spec)\.\w+)$", name))


def _command(policy: RepoPolicy, path: str) -> str | None:
    """`path` written as a command for the repo's test runner, or None."""
    suites = list(policy.dev_suites.values())
    if path.endswith(".py"):
        for s in suites:
            m = re.search(r"((?:[\w.-]+ )*?pytest)\b", s.split("&&")[-1] if "&&" in s else s)
            if m:
                return f"{m.group(1)} -q {path}"
        return f"pytest -q {path}"
    for s in suites:
        for m in re.finditer(r"pnpm -C (\S+) test(?![:\w-])", s):
            d = m.group(1).rstrip("/")
            if path.startswith(d + "/"):
                return f"pnpm -C {d} test {path[len(d) + 1 :]}"
    return None


def compute_prefill(
    repo: Path,
    request: Mapping[str, Any],
    *,
    policy: RepoPolicy,
    money_globs: Sequence[str],
    issue: str = "",
) -> Prefill:
    """What vigild can fill in before the coord: `repo` is the coord's fresh clone
    at base_sha, `request` the coord's request contract (title, request, notes),
    `issue` the fetched issue text, if any."""
    hints = request_paths(
        {
            "title": request.get("title"),
            "request": request.get("request"),
            "notes": [*(request.get("notes") or []), issue],
        }
    )
    text = "\n".join(
        [str(request.get("title") or ""), str(request.get("request") or "")]
        + [str(n) for n in request.get("notes") or []]
        + [issue]
    )
    pre = Prefill()
    for h in hints:
        if _is_file(repo, h):
            if _excluded(text, h):
                if h not in pre.out_of_scope:
                    pre.out_of_scope.append(h)
                continue
            if h not in pre.candidates and len(pre.candidates) < MAX_CANDIDATES:
                pre.candidates.append(h)
        elif "/" in h or h.endswith(FILE_SUFFIXES):
            why = "a glob; candidates are files" if set("*?[") & set(h) else "no such file"
            pre.dropped.append(f"`{h}` ({why} at base_sha)")
    pre.dropped = pre.dropped[:MAX_DROPPED]
    pre.money_paths = [c for c in pre.candidates if matches_any(c, money_globs)]
    pre.pinned_paths = [c for c in pre.candidates if in_scope(c, policy.ladder_pinned_paths)]

    tracked = _files(repo)
    tests: list[str] = []
    for c in pre.candidates:
        name = c.rsplit("/", 1)[-1]
        if _is_test_file(name):
            tests.append(c)
            continue
        stem = name.split(".")[0]
        if stem == "__init__":
            continue
        found = [
            f
            for f in tracked
            if any(fnmatchcase(f.rsplit("/", 1)[-1], p) for p in _test_patterns(stem))
        ]
        tests += sorted(found)[:MAX_TESTS_PER_STEM]
    cmds = list(policy.dev_suites.values())
    cmds += [cmd for t in dict.fromkeys(tests) if (cmd := _command(policy, t))]
    pre.test_cmds = list(dict.fromkeys(cmds))
    runner: set[str] = set()
    for cmd in pre.test_cmds or [""]:
        runner |= set(runner_overlap(pre.candidates, policy.runner_config, cmd))
    pre.runner_files = [c for c in pre.candidates if c in runner]
    return pre

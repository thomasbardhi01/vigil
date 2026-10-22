"""The verifier: the only source of test results (owner direction, review
rounds 2 and 3).

After a worker exits and its branch is in the vault, vigild runs the task's
`test_cmd` itself, never trusting anything the worker's container wrote:

- **after:** the head commit, checked out fresh from the vault into a
  directory vigild owns, with a new `.git` whose `core.hooksPath` is /dev/null.
- **before** (when `must_fail_first`): the base commit with the worker's new
  and changed test files (paths `TEST_FILE` matches, taken from the head) laid
  over it, so a new test exists but the code it tests doesn't. Deleted test
  files aren't restored; `weakened_tests` rejects those anyway.
- **One runner config for both** (round 3, F1): files that decide how tests
  run (the repo's `runner_config` globs, plus any script `test_cmd` itself
  invokes) are the base's in both runs, except files the approved spec names
  by path; those are the head's in both runs. A worker can't make "after"
  pass by rewriting the runner, and acceptance rejects the attempt.
- **What a result means** (round 3, F3): `judge` maps runner exits that aren't
  test results (pytest 2-5, vitest's "no test files", a signal) to `unknown`.
  pytest and a directly invoked vitest are asked for a JUnit report, written
  to the container's tmpfs and streamed back after the output; when both runs
  have one, must-fail-first means at least one of the worker's new or changed
  tests failed "before" and every one of those passes "after". Without a
  report the exit codes decide and the record says the ids weren't checked.

Each run gets its own checkout and its own container from the repo's dev image
(never the session image): no network, read-only checkout, the agent uid,
output capped. vigild reads the container's output stream itself; nothing is
read back from a path. The checkout is removed after the run.

A report comes from test code the worker wrote, running as the same uid, so it
is evidence of which tests failed, not a defence against a hostile test.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from vigild.intake.paths import in_scope
from vigild.shellwords import Command, parse
from vigild.workspace import Workspace

VERIFY_SECONDS = 15 * 60
# ParkAgent's full server suite reports 1853 cases in a 376 KB JUnit file
# (measured 2026-10-22); 8 MiB per report is ~20x headroom.
MAX_OUTPUT = 24 << 20  # the output's tail plus the reports, base64
MAX_REPORT = 8 << 20
TAIL = 2000
REPORT_DIR = "/tmp/vigil-report"  # noqa: S108  (the verifier container's own tmpfs)
TEST_FILE = re.compile(
    r"(^|/)(tests?/|__tests__/|test_[^/]*$|[^/]*_test\.[a-z]+$|[^/]*\.(test|spec)\.[a-z]+$)"
)
INTERPRETERS = {"sh", "bash", "dash", "zsh", "python", "python3", "node", "tsx", "deno", "perl"}
PYTEST_NOT_A_RESULT = {2, 3, 4, 5}  # interrupted/collection error, internal, usage, no tests
VITEST_NO_FILES = "No test files found"


@dataclass(frozen=True)
class RunResult:
    exit: int | None
    output: str
    timed_out: bool = False
    truncated: bool = False
    reports: dict[str, bytes] = field(default_factory=dict)


class TestRunner(Protocol):
    def run(
        self, image: str, source: Path, command: str, *, timeout_s: int, max_output: int
    ) -> RunResult: ...


def outcome(code: int | None, timed_out: bool) -> str:
    if timed_out:
        return "timeout"
    if code == 0:
        return "pass"
    if code in (125, 126, 127) or (code is not None and code >= 128):
        return "unknown"  # couldn't prepare (125) or run (126/127); killed by a signal
    return "fail"


def runs_pytest(test_cmd: str) -> bool:
    return any(
        "pytest" in (c.program, *(w.rsplit("/", 1)[-1] for w in c.args[:3]))
        for c in parse(test_cmd).commands
    )


def judge(test_cmd: str, code: int | None, timed_out: bool, output: str) -> str:
    """The outcome, with a runner's own non-test exits read as `unknown`."""
    got = outcome(code, timed_out)
    if got != "fail":
        return got
    if runs_pytest(test_cmd) and code in PYTEST_NOT_A_RESULT:
        return "unknown"
    if VITEST_NO_FILES in output:
        return "unknown"
    return got


def _script(words: list[str]) -> str:
    """The repo file a command runs as its program, if any: the program
    itself when it's a relative path, or an interpreter's script argument.
    Never a test runner's arguments (round 4, item 2)."""
    if not words:
        return ""
    prog, rest = words[0], words[1:]
    base = prog.rsplit("/", 1)[-1]
    if "/" in prog and not prog.startswith("/") and base not in INTERPRETERS:
        return prog
    if base in INTERPRETERS:
        for a in rest:
            if a in ("-c", "-m"):
                return ""  # code or a module, not a file
            if not a.startswith("-"):
                return a
        return ""
    if base == "uv" and rest[:1] == ["run"]:
        args = [a for a in rest[1:] if not a.startswith("-")]
        if args and args[0].endswith((".py", ".sh")):
            return args[0]
        return _script(args)  # `uv run python x.py`; `uv run pytest …` names no script
    if base == "make":
        return "Makefile"
    return ""


def invoked_scripts(test_cmd: str) -> list[str]:
    """Repo files `test_cmd` runs as programs: `./x.sh`, `sh run_tests.sh`,
    `python tools/check.py`, `uv run x.py`, a Makefile. Arguments to a test
    runner (`pytest tests/test_a.py`, `uv run pytest tests/test_a.py`) are
    tests, not runner config."""
    out: list[str] = []
    for c in parse(test_cmd).commands:
        script = _script([c.program, *c.args] if c.program else [])
        if not script:
            first = next((w for w in c.words if w.rsplit("/", 1)[-1] == c.program), "")
            if "/" in first and not first.startswith("/"):
                script = first
        if script and not script.startswith("/"):
            out.append(script)
    return sorted({p.removeprefix("./") for p in out})


PACKAGE_MANAGERS = {"pnpm", "npm", "yarn"}
ReadFile = Callable[[str], str | None]


def _package_script(c: Command, read: ReadFile) -> str:
    """The script a `pnpm -C server test` / `npm run test` command runs, read
    from the base's package.json (what the verifier pins)."""
    args = list(c.args)
    where = ""
    for flag in ("-C", "--dir", "--prefix"):
        if flag in args and args.index(flag) + 1 < len(args):
            k = args.index(flag)
            where = args[k + 1]
            del args[k : k + 2]
    rest = [a for a in args if not a.startswith("-")]
    if rest[:1] == ["run"]:
        rest = rest[1:]
    if not rest:
        return ""
    raw = read(f"{where.rstrip('/')}/package.json" if where else "package.json")
    try:
        scripts = json.loads(raw or "{}").get("scripts") or {}
    except json.JSONDecodeError, AttributeError:
        return ""
    return str(scripts.get(rest[0]) or "")


def can_report(test_cmd: str) -> bool:
    """Does some command in the line run a test runner the verifier can read:
    pytest, vitest, or a package manager's script (whose runner the verifier
    finds in the base's package.json)?"""
    for c in parse(test_cmd).commands:
        args = [a.rsplit("/", 1)[-1] for a in c.args]
        if c.program in ("pytest", "vitest") or "pytest" in args or "vitest" in args:
            return True
        if c.program in PACKAGE_MANAGERS and any(a in ("test", "run") for a in args[:4]):
            return True
    return False


def _dir_option(c: Command) -> str:
    args = list(c.args)
    for flag in ("-C", "--dir", "--prefix"):
        if flag in args and args.index(flag) + 1 < len(args):
            return f"{flag} {shlex.quote(args[args.index(flag) + 1])} "
    return ""


def with_reports(test_cmd: str, read: ReadFile | None = None) -> str:
    """Ask each vitest run for a JUnit report too. A direct `vitest run` gets
    the flags appended. A pnpm script that ends in vitest runs as
    `pnpm exec bash -c '<the base's script> <flags>'`, since pnpm reads
    `--reporter` as its own option; npm passes arguments after `--` on.
    pytest gets its report through PYTEST_ADDOPTS in the container's environment."""
    out, pos, n = [], 0, 0
    for c in parse(test_cmd).commands:
        direct = c.program == "vitest" or ("vitest" in c.args and "run" in c.args)
        script = _package_script(c, read) if read and c.program in PACKAGE_MANAGERS else ""
        last = parse(script).commands[-1] if script.strip() else None
        via_script = last is not None and (
            last.program == "vitest" or ("vitest" in last.args and "run" in last.args)
        )
        if not (direct or via_script):
            continue
        n += 1
        flags = (
            f" --reporter=default --reporter=junit --outputFile.junit={REPORT_DIR}/vitest-{n}.xml"
        )
        end = c.start + len(c.text.rstrip())
        if direct:
            out.append(test_cmd[pos:end] + flags)
        elif c.program == "pnpm":
            inner = shlex.quote(script + flags)
            run = f"pnpm {_dir_option(c)}exec bash -o pipefail -o errexit -c {inner}"
            out.append(test_cmd[pos : c.start] + c.text[: len(c.text) - len(c.text.lstrip())] + run)
        else:  # npm and yarn pass extra arguments to the script
            out.append(test_cmd[pos:end] + (" --" if c.program == "npm" else "") + flags)
        pos = end
    out.append(test_cmd[pos:])
    return "".join(out)


@dataclass(frozen=True)
class Case:
    id: str
    file: str
    status: str  # pass | failure | error | skipped | xfail


def parse_junit(data: bytes) -> list[Case]:
    if len(data) > MAX_REPORT or b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        return []
    try:
        root = ET.fromstring(data)  # noqa: S314 (no DTDs or entities, size-capped)
    except ET.ParseError:
        return []
    cases: list[Case] = []
    for tc in root.iter("testcase"):
        classname = tc.get("classname", "")
        status = "pass"
        for tag in ("failure", "error", "skipped"):
            el = tc.find(tag)
            if el is not None:
                xfail = "xfail" in (el.get("type", "") + el.get("message", "")).lower()
                status = "xfail" if tag == "skipped" and xfail else tag
                break
        cases.append(
            Case(f"{classname}::{tc.get('name', '')}", tc.get("file") or classname, status)
        )
    return cases


def belongs(case: Case, files: Iterable[str]) -> bool:
    """Is a report's test case in one of these repo files? pytest names a
    module (`tests.test_a`); vitest a path relative to its project dir."""
    guesses = {case.file, case.file.replace(".", "/") + ".py"}
    for f in files:
        for g in guesses:
            if g and (f == g or f.endswith("/" + g)):
                return True
    return False


def compare_runs(base: list[Case], head: list[Case]) -> dict[str, Any]:
    """What ran at head against what ran at base, with the same command and the
    same runner config (owner direction, round 3): head may add tests; it may
    never run fewer ids or files, or skip or xfail more."""
    ids_b, ids_h = {c.id for c in base}, {c.id for c in head}
    files_b, files_h = {c.file for c in base}, {c.file for c in head}

    def count(cases: list[Case], status: str) -> int:
        return sum(1 for c in cases if c.status == status)

    out: dict[str, Any] = {
        "checked": True,
        "ids": {"base": len(ids_b), "head": len(ids_h)},
        "missing_ids": sorted(ids_b - ids_h)[:50],
        "missing_files": sorted(files_b - files_h)[:50],
        "skipped": {"base": count(base, "skipped"), "head": count(head, "skipped")},
        "xfail": {"base": count(base, "xfail"), "head": count(head, "xfail")},
    }
    out["ok"] = not (
        out["missing_ids"]
        or out["missing_files"]
        or out["skipped"]["head"] > out["skipped"]["base"]
        or out["xfail"]["head"] > out["xfail"]["base"]
    )
    return out


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
        runner_config: Iterable[str] = (),
    ) -> dict[str, Any]:
        """`test_cmd` is the approved spec's, never the worker's tree's."""
        base_files = self.ws.tree_paths(repo, base_sha)
        head_files = self.ws.tree_paths(repo, head)
        globs = list(runner_config)
        # The runner files, from the base, in every run (owner direction, round 3):
        # the repo's runner_config, and any script test_cmd runs that the base has.
        pinned = sorted(
            {p for p in base_files | head_files if in_scope(p, globs)}
            | {p for p in invoked_scripts(test_cmd) if p in base_files}
        )
        changed = self.ws.changed(repo, base_sha, head)
        changed_paths = {path for _, path in changed}
        tests = sorted(
            path
            for status, path in changed
            if status[:1] in ("A", "M") and TEST_FILE.search(path) and path not in pinned
        )
        record: dict[str, Any] = {
            "test_cmd": test_cmd,
            "runner_config": {"pinned_to_base": [p for p in pinned if p in changed_paths]},
        }
        command = with_reports(test_cmd, lambda path: self.ws.read_blob(repo, base_sha, path))
        pin = (base_sha, pinned)
        base = self._run(repo, image, f"{task_id}-base", base_sha, test_cmd, command, [pin])
        record["base"] = base
        before: dict[str, Any] | None = None
        if must_fail_first:
            before = self._run(
                repo, image, f"{task_id}-before", base_sha, test_cmd, command,
                [(head, tests), pin],
            )  # fmt: skip
            before["applied"] = tests
            record["before"] = before
        after = self._run(repo, image, f"{task_id}-after", head, test_cmd, command, [pin])
        if not after["_report"] and after["outcome"] == "pass":
            # owner direction, round 3: "tests ran" can't be confirmed without a report
            after["outcome"] = "unknown"
            after["note"] = "no test report: that any test ran can't be confirmed"
        record["after"] = after
        added = sorted(path for status, path in changed if status[:1] == "A")
        if not after["_report"]:
            record["ran"] = {"checked": False, "note": "no report from the head run"}
        elif base["_report"]:
            record["ran"] = {**compare_runs(base["_cases"], after["_cases"]), "against": "base"}
        elif before is not None and before["_report"]:
            # round 4, item 4: base ran no runner (e.g. a check before it failed);
            # compare with "before" minus the tests the worker added
            kept = [c for c in before["_cases"] if not belongs(c, added)]
            record["ran"] = {**compare_runs(kept, after["_cases"]), "against": "before"}
        else:
            record["ran"] = {
                "checked": False,
                "unknown": True,
                "note": "neither base nor before produced a report: what ran can't be compared",
            }
        if before is not None:
            record["ids"] = self._ids(before, after, tests)
        record["provenance"] = "human"  # observed by vigild, not reported by the model
        record["source"] = "verifier"
        for run in (base, before, after):
            if run is not None:
                run.pop("_cases", None)
                run.pop("_report", None)
        return record

    @staticmethod
    def _ids(before: dict[str, Any], after: dict[str, Any], tests: list[str]) -> dict[str, Any]:
        b, a = before.get("_cases"), after.get("_cases")
        if not before.get("_report") or not after.get("_report"):
            return {"checked": False, "note": "test ids not checked: the runner gave no report"}
        failing = sorted(
            c.id for c in b or [] if c.status in ("failure", "error") and belongs(c, tests)
        )
        passing = {c.id for c in a or [] if c.status == "pass"}
        return {
            "checked": True,
            "failing_before": failing,
            "not_passing_after": sorted(i for i in failing if i not in passing),
        }

    def _run(
        self,
        repo: str,
        image: str,
        name: str,
        sha: str,
        test_cmd: str,
        command: str,
        take: list[tuple[str, list[str]]],
    ) -> dict[str, Any]:
        src = self.ws.verify_checkout(repo, name, sha, take=take)
        try:
            r = self.runner.run(
                image, src, command, timeout_s=self.timeout_s, max_output=MAX_OUTPUT
            )
        finally:
            shutil.rmtree(src.parent, ignore_errors=True)
        cases = [c for data in r.reports.values() for c in parse_junit(data)]
        got = judge(test_cmd, r.exit, r.timed_out, r.output)
        out: dict[str, Any] = {
            "sha": sha,
            "exit": r.exit,
            "outcome": got,
            "tail": r.output[-TAIL:],
            "tests": len(cases),
            "_cases": cases,
            "_report": bool(r.reports),
        }
        if r.reports and not cases and got == "pass":
            out["outcome"] = "unknown"  # exit 0 with no test run is not a pass (round 3)
            out["note"] = "the report lists no tests"
        failing = [c.id for c in cases if c.status in ("failure", "error")]
        if failing and got == "pass":
            # round 4, item 1: `! pytest`, `if pytest; …`, `set +e`, a trap or
            # `&& …; echo` can exit 0 while tests fail; the report decides
            out["outcome"] = "fail"
            out["note"] = f"exit 0, but the report has {len(failing)} failing test(s)"
        if r.truncated:
            out["truncated"] = True
        return out

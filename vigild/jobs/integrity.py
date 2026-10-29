"""Stage 3 completion-integrity check (#104): five rules, no model call.

Pure functions over the task's diff (unified-diff text vigild read from its
vault through `Workspace.diff`) and over the worker report. A finding names
its rule and file:line and pages the job like "test weakened"; nothing is
auto-fixed. Every snippet from the diff or the report is untrusted, so it goes
through `redact` and is cut short; findings that reach a packet are fenced by
the packet builder (`packets.fence`).

Rules: todo-without-issue, skip-without-reason, stub, self-referential-evidence,
guard-removed. Each heuristic is narrow on purpose: a false negative is better
than noise."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from vigild.contract.models import WorkerReport
from vigild.redact import redact
from vigild.verifier import TEST_FILE
from vigild.workspace import Workspace, WorkspaceError

# Rule 4: kept small. Matched case-insensitively in the report's free text.
SELF_REFERENTIAL = (
    "works as expected",
    "manually verified",
    "verified manually",
    "tested manually",
    "looks correct",
)

PROSE = (".md", ".rst", ".txt", ".json", ".lock")
ISSUE_REF = re.compile(r"#\d+|/(?:issues|pull)/\d+")
MARKER = re.compile(r"#|//|/\*|<!--")
TODO_WORD = re.compile(r"\b(?:TODO|FIXME|WIP)\b")
STAR_COMMENT = re.compile(r"^\s*\*")
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
PY_SKIP = re.compile(r"pytest\.mark\.(?:skip|skipif|xfail)\b")
JS_SKIP = re.compile(r"\b(?:it|test|describe|suite)(?:\.\w+)*\.(?:skip|only)\(")
REASON = re.compile(r"\breason\s*=")
STUB_WORD = re.compile(r"\bstub\b", re.I)
TEST_NAMED = re.compile(r"\btest_\w+|\S+::\w+")
NIE_BASES = re.compile(r"\b(?:Protocol|ABC|ABCMeta)\b")
NIE_DECORATORS = re.compile(r"@(?:[\w.]*\.)?(?:abstractmethod|overload)\b")
RUST_IGNORE = re.compile(r"#\[ignore\s*\]")
GO_SKIP = re.compile(r"\bt\.Skip\(\s*\)")
RAISE_NIE = re.compile(r"\braise\s+NotImplementedError\b")
TODO_MACRO = re.compile(r"\btodo!\s*\(")
STUB_BODY = re.compile(r"^\s*(?:pass|\.\.\.)\s*(?:#.*)?$")
# Rule 5: removed lines that were a validation or an allowlist, or a refusal test.
GUARD = re.compile(
    r"\b(?:validate\w*|is_valid\w*)\b"
    r"|\b(?:[A-Z][A-Z0-9]*_)+(?:ALLOW|ALLOWED|ALLOWLIST|DENY|BLOCKLIST)\b"
    r"|\b(?:ALLOW|ALLOWED|ALLOWLIST|DENY|BLOCKLIST)(?:_[A-Z0-9]+)+\b"
    r"|\braise\s+(?:ValueError|PermissionError)\b"
)
RAISE = re.compile(r"\s*raise\s+\w+")
DELETED = re.compile(r"^\+\+\+ /dev/null", re.M)
REFUSAL_TEST = re.compile(r"\bdef\s+test_refuses_\w+|\b(?:it|test)\(\s*['\"]refuses\b")
NEGATIVE_TEST = re.compile(
    r"\bdef\s+test_(?:refuses_|rejects_)|\bdef\s+test_\w*_(?:is_)?refused\b"
    r"|\bdef\s+test_\w*_raises\b|pytest\.raises\b|assertRaises|toThrow\(|\.rejects\b"
)


@dataclass(frozen=True)
class Line:
    kind: str  # "+", "-" or " "
    no: int  # new-file number for + and context, old-file for -
    text: str


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    line: int | None
    snippet: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"completion integrity: {self.rule} {where}: {self.snippet}"


def _snippet(text: str) -> str:
    return str(redact(text.strip()))[:80]


def parse(diff: str) -> list[Line]:
    out: list[Line] = []
    old = new = 0
    started = False
    for raw in diff.splitlines():
        m = HUNK.match(raw)
        if m:
            old, new, started = int(m.group(1)), int(m.group(2)), True
        elif not started or not raw or raw[0] not in "+- " or raw.startswith(("+++", "---")):
            continue
        elif raw[0] == "+":
            out.append(Line("+", new, raw[1:]))
            new += 1
        elif raw[0] == "-":
            out.append(Line("-", old, raw[1:]))
            old += 1
        else:
            out.append(Line(" ", new, raw[1:]))
            old += 1
            new += 1
    return out


def _joined(lines: list[Line], i: int) -> str:
    """The added line plus the added lines after it until its parens balance."""
    text = lines[i].text
    j = i
    while text.count("(") > text.count(")") and j + 1 < len(lines) and lines[j + 1].kind == "+":
        j += 1
        text += " " + lines[j].text
    return text


def _add(out: list[Finding], path: str, ln: Line, rule: str) -> None:
    out.append(Finding(rule, path, ln.no, _snippet(ln.text)))


def _comment_todo(t: str) -> bool:
    """A TODO in a real comment: the marker starts the line, or the code before
    it has balanced quotes (and no open backtick), and `//` does not follow `:`."""
    if STAR_COMMENT.match(t) and TODO_WORD.search(t):
        return True
    for m in MARKER.finditer(t):
        pre = t[: m.start()]
        if m.group() == "//" and pre.endswith(":"):
            continue
        quoted = pre.count("'") % 2 or pre.count('"') % 2 or pre.count("`") % 2
        if (not pre.strip() or not quoted) and TODO_WORD.search(t[m.start() :]):
            return True
    return False


def _nie_exempt(src: list[str], idx: int) -> bool:
    """Is the `raise` at src[idx] inside an abstract/overload def or a
    Protocol/ABC class? Walks outward by indentation."""

    def indent(x: str) -> int:
        return len(x) - len(x.lstrip())

    level = indent(src[idx])
    for j in range(idx - 1, -1, -1):
        text = src[j]
        if not text.strip() or indent(text) >= level:
            continue
        level = indent(text)
        head = text.strip()
        if head.startswith(("def ", "async def ")):
            k = j - 1
            while k >= 0 and src[k].strip().startswith("@") and indent(src[k]) == level:
                if NIE_DECORATORS.search(src[k]):
                    return True
                k -= 1
        elif head.startswith("class ") and NIE_BASES.search(head):
            return True
        if level == 0:
            break
    return False


def _file_findings(
    path: str, lines: list[Line], full: Callable[[], str | None] = lambda: None
) -> list[Finding]:
    out: list[Finding] = []
    prose = path.lower().endswith(PROSE)
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    for i, ln in enumerate(lines):
        if ln.kind != "+":
            continue
        t = ln.text
        add = partial(_add, out, path, ln)

        if not prose and _comment_todo(t) and not ISSUE_REF.search(t):
            add("todo-without-issue")
        if ext == "py" and PY_SKIP.search(t) and not REASON.search(_joined(lines, i)):
            add("skip-without-reason")
        elif (
            ext in ("js", "jsx", "ts", "tsx", "mjs", "cjs")
            and TEST_FILE.search(path)
            and JS_SKIP.search(t)
        ):
            if not ISSUE_REF.search(t):
                add("skip-without-reason")
        elif (ext == "rs" and RUST_IGNORE.search(t)) or (ext == "go" and GO_SKIP.search(t)):
            add("skip-without-reason")
        if prose:
            continue
        if ext == "py" and RAISE_NIE.search(t):
            if not TEST_FILE.search(path) and not _nie_exempt_at(lines, i, ln, full):
                add("stub")
        elif ext == "rs" and TODO_MACRO.search(t):
            add("stub")
        elif ext == "py" and STUB_BODY.match(t):
            prev = lines[i - 1] if i > 0 and lines[i - 1].kind == "+" else None
            marked = bool(re.search(r"#.*\bstub\b", t, re.I)) or bool(
                prev and prev.text.lstrip().startswith("#") and STUB_WORD.search(prev.text)
            )
            if marked:
                add("stub")
    return out


def _nie_exempt_at(lines: list[Line], i: int, ln: Line, full: Callable[[], str | None]) -> bool:
    text = full()
    if text is not None:
        src = text.splitlines()
        if 0 < ln.no <= len(src) and src[ln.no - 1].strip() == ln.text.strip():
            return _nie_exempt(src, ln.no - 1)
    new = [(k, x.text) for k, x in enumerate(lines) if x.kind != "-"]
    pos = next(n for n, (k, _) in enumerate(new) if k == i)
    return _nie_exempt([x for _, x in new], pos)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _guard_findings(diffs: dict[str, list[Line]], deleted: frozenset[str]) -> list[Finding]:
    """A removed validation, allowlist or refusal test with no negative test
    added anywhere in the diff, and (for code) no guard line added back in the
    same file. Heuristic and narrow: renames of a guard count as edits."""
    if any(NEGATIVE_TEST.search(ln.text) for ls in diffs.values() for ln in ls if ln.kind == "+"):
        return []
    out: list[Finding] = []
    added_all = Counter(_norm(ln.text) for ls in diffs.values() for ln in ls if ln.kind == "+")
    for path, lines in diffs.items():
        if path in deleted or path.lower().endswith(PROSE):
            continue
        pat = REFUSAL_TEST if TEST_FILE.search(path) else GUARD
        added_raise = any(ln.kind == "+" and RAISE.match(ln.text) for ln in lines)
        pending: list[Line] = []
        for ln in lines:
            if ln.kind != "-" or not pat.search(ln.text):
                continue
            n = _norm(ln.text)
            if added_all[n] > 0:
                added_all[n] -= 1
            elif added_raise and RAISE.match(ln.text):
                continue
            else:
                pending.append(ln)
        added = sum(1 for ln in lines if ln.kind == "+" and pat.search(ln.text))
        if pending and added < len(pending):
            out.append(Finding("guard-removed", path, pending[0].no, _snippet(pending[0].text)))
    return out


def check(diffs: dict[str, str], full: Callable[[str], str | None] | None = None) -> list[Finding]:
    """Rules 1, 2, 3 and 5 over `{path: unified diff}`. `full(path)` reads the
    new file's text (vault blob) when the caller can."""
    parsed = {p: parse(d) for p, d in diffs.items()}
    deleted = frozenset(p for p, d in diffs.items() if DELETED.search(d))
    out: list[Finding] = []
    for path, lines in parsed.items():
        out += _file_findings(path, lines, partial(full, path) if full else lambda: None)
    return out + _guard_findings(parsed, deleted)


def report_findings(report: WorkerReport) -> list[Finding]:
    """Rule 4: the report's free text offers its own say-so as evidence."""
    sc = report.self_check
    fields = {
        "summary": report.summary,
        "self_check.not_done": sc.not_done,
        "self_check.reviewer_would_flag": sc.reviewer_would_flag,
        "self_check.could_delete": sc.could_delete,
    }
    out: list[Finding] = []
    for name, text in fields.items():
        low = text.lower()
        if TEST_NAMED.search(text):
            continue
        for phrase in SELF_REFERENTIAL:
            if phrase in low:
                out.append(
                    Finding("self-referential-evidence", f"worker_report.json:{name}", None, phrase)
                )
                break
    return out


def check_integrity(
    ws: Workspace, repo: str, base_sha: str, head: str, report: WorkerReport
) -> list[str]:
    """The acceptance hook: finding messages, the way "test weakened" reports."""
    paths = sorted({p for _, p in ws.changed(repo, base_sha, head)})
    diffs = {p: ws.diff(repo, base_sha, head, p) for p in paths}

    def full(path: str) -> str | None:
        try:
            return ws.read_blob(repo, head, path)
        except WorkspaceError:
            return None

    return [str(f) for f in [*check(diffs, full), *report_findings(report)]]

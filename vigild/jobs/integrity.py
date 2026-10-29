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
from dataclasses import dataclass
from functools import partial

from vigild.contract.models import WorkerReport
from vigild.redact import redact
from vigild.verifier import TEST_FILE
from vigild.workspace import Workspace

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
COMMENT_TODO = re.compile(r"(?:#|//|/\*|<!--|^\s*\*)[^\n]*?\b(?:TODO|FIXME|WIP)\b")
HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
PY_SKIP = re.compile(r"pytest\.mark\.(?:skip|skipif|xfail)\b")
JS_SKIP = re.compile(r"\.(?:skip|only)\(")
RUST_IGNORE = re.compile(r"#\[ignore\s*\]")
GO_SKIP = re.compile(r"\bt\.Skip\(\s*\)")
RAISE_NIE = re.compile(r"\braise\s+NotImplementedError\b")
TODO_MACRO = re.compile(r"\btodo!\s*\(")
STUB_BODY = re.compile(r"^\s*(?:pass|\.\.\.)\s*(?:#.*)?$")
ABSTRACT = re.compile(r"abstractmethod")
# Rule 5: removed lines that were a validation or an allowlist, or a refusal test.
GUARD = re.compile(
    r"\b(?:validate\w*|is_valid\w*|allowlist|allow_list|ALLOWED\w*)\b"
    r"|\braise\s+(?:ValueError|PermissionError)\b"
)
REFUSAL_TEST = re.compile(r"\bdef\s+test_refuses_\w+|\b(?:it|test)\(\s*['\"]refuses\b")
NEGATIVE_TEST = re.compile(
    r"\bdef\s+test_\w*(?:refus|reject|den(?:y|ies)|rais|fail|block|invalid|never|not_)\w*"
    r"|pytest\.raises\(|assertRaises|toThrow\(|\.rejects\b"
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


def _file_findings(path: str, lines: list[Line]) -> list[Finding]:
    out: list[Finding] = []
    prose = path.lower().endswith(PROSE)
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    for i, ln in enumerate(lines):
        if ln.kind != "+":
            continue
        t = ln.text
        add = partial(_add, out, path, ln)

        if not prose and COMMENT_TODO.search(t) and not ISSUE_REF.search(t):
            add("todo-without-issue")
        if ext == "py" and PY_SKIP.search(t) and "reason" not in _joined(lines, i):
            add("skip-without-reason")
        elif ext in ("js", "jsx", "ts", "tsx", "mjs", "cjs") and JS_SKIP.search(t):
            if not ISSUE_REF.search(t):
                add("skip-without-reason")
        elif (ext == "rs" and RUST_IGNORE.search(t)) or (ext == "go" and GO_SKIP.search(t)):
            add("skip-without-reason")
        if prose:
            continue
        if ext == "py" and RAISE_NIE.search(t):
            if not any(ABSTRACT.search(p.text) for p in lines[max(0, i - 8) : i]):
                add("stub")
        elif ext == "rs" and TODO_MACRO.search(t):
            add("stub")
        elif ext == "py" and STUB_BODY.match(t):
            prev = lines[i - 1] if i > 0 and lines[i - 1].kind == "+" else None
            marked = "stub" in t.lower() or bool(
                prev and prev.text.lstrip().startswith("#") and "stub" in prev.text.lower()
            )
            if marked:
                add("stub")
    return out


def _guard_findings(diffs: dict[str, list[Line]]) -> list[Finding]:
    """A removed validation, allowlist or refusal test with no negative test
    added anywhere in the diff, and (for code) no guard line added back in the
    same file. Heuristic and narrow: renames of a guard count as edits."""
    if any(NEGATIVE_TEST.search(ln.text) for ls in diffs.values() for ln in ls if ln.kind == "+"):
        return []
    out: list[Finding] = []
    for path, lines in diffs.items():
        is_test = bool(TEST_FILE.search(path))
        pat = REFUSAL_TEST if is_test else GUARD
        if path.lower().endswith(PROSE):
            continue
        removed = [ln for ln in lines if ln.kind == "-" and pat.search(ln.text)]
        added = sum(1 for ln in lines if ln.kind == "+" and pat.search(ln.text))
        if removed and added < len(removed):
            out.append(Finding("guard-removed", path, removed[0].no, _snippet(removed[0].text)))
    return out


def check(diffs: dict[str, str]) -> list[Finding]:
    """Rules 1, 2, 3 and 5 over `{path: unified diff}`."""
    parsed = {p: parse(d) for p, d in diffs.items()}
    out: list[Finding] = []
    for path, lines in parsed.items():
        out += _file_findings(path, lines)
    return out + _guard_findings(parsed)


def report_findings(report: WorkerReport) -> list[Finding]:
    """Rule 4: the report's free text offers its own say-so as evidence."""
    sc = report.self_check
    fields = {
        "summary": report.summary,
        "self_check.not_done": sc.not_done,
        "self_check.reviewer_would_flag": sc.reviewer_would_flag,
        "self_check.could_delete": sc.could_delete,
        **{f"open_questions[{i}]": q for i, q in enumerate(report.open_questions)},
    }
    out: list[Finding] = []
    for name, text in fields.items():
        low = text.lower()
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
    return [str(f) for f in [*check(diffs), *report_findings(report)]]

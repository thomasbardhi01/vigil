"""The rules-only completion-integrity check (#104): each rule has a positive
test and a near-miss negative test. Pure functions over diff text."""

from __future__ import annotations

from vigild.contract.models import WorkerReport
from vigild.jobs.integrity import check, report_findings


def _diff(
    path: str, added: list[str], removed: list[str] | None = None, ctx: list[str] | None = None
) -> dict[str, str]:
    """A one-hunk unified diff: context, then removed, then added lines."""
    ctx = ctx or []
    removed = removed or []
    body = [f" {c}" for c in ctx] + [f"-{r}" for r in removed] + [f"+{a}" for a in added]
    head = f"@@ -10,{len(ctx) + len(removed)} +20,{len(ctx) + len(added)} @@\n"
    return {path: head + "\n".join(body) + "\n"}


def _rules(diffs: dict[str, str]) -> list[str]:
    return [f.rule for f in check(diffs)]


def _report(**kw: str) -> WorkerReport:
    sc = {"test_failed_first": True, "outside_scope": [], "not_done": "-",
          "reviewer_would_flag": "-", "could_delete": "-"}  # fmt: skip
    sc.update({k: v for k, v in kw.items() if k in sc})
    return WorkerReport.model_validate({
        "task_id": "t", "job_id": "j", "files_changed": [], "summary": kw.get("summary", "s"),
        "self_check": sc, "provenance": "claude",
    })  # fmt: skip


# 1 todo
def test_bare_todo_fires_with_file_and_line() -> None:
    [f] = check(_diff("a.py", ["x = 1", "y = 2  # TODO tidy"]))
    assert (f.rule, f.path, f.line) == ("todo-without-issue", "a.py", 21)
    assert str(f).startswith("completion integrity: todo-without-issue a.py:21")


def test_todo_with_an_issue_ref_or_outside_a_comment_is_quiet() -> None:
    assert _rules(_diff("a.py", ["# TODO(#12): tidy"])) == []
    assert _rules(_diff("a.py", ["// FIXME https://github.com/o/r/issues/9"])) == []
    assert _rules(_diff("a.py", ["name = 'TODO list'"])) == []
    assert _rules(_diff("notes.md", ["# TODO later"])) == []


# 2 skip and focus
def test_new_skips_without_a_reason_fire() -> None:
    cases = {
        "t.py": ["@pytest.mark.skip", "@pytest.mark.skipif(sys.platform == 'win32')",
                 "@pytest.mark.xfail(strict=True)"],
        "a.test.ts": ["it.skip('x', () => {})", "describe.only('y', () => {})"],
        "lib.rs": ["#[ignore]"],
        "x_test.go": ["t.Skip()"],
    }  # fmt: skip
    for path, lines in cases.items():
        for line in lines:
            assert _rules(_diff(path, [line])) == ["skip-without-reason"], line


def test_skips_with_a_reason_are_quiet() -> None:
    assert _rules(_diff("t.py", ["@pytest.mark.skip(reason='needs docker')"])) == []
    assert _rules(_diff("t.py", ["@pytest.mark.skipif(x, reason='y')"])) == []
    assert _rules(_diff("t.py", ["@pytest.mark.xfail(", "    reason='z')"])) == []
    assert _rules(_diff("a.test.ts", ["it.skip('x', f) // #44"])) == []
    assert _rules(_diff("lib.rs", ['#[ignore = "slow"]'])) == []
    assert _rules(_diff("x_test.go", ['t.Skip("needs network")'])) == []
    assert _rules(_diff("t.py", [], removed=["@pytest.mark.skip"])) == []


# 3 stubs
def test_stubs_fire() -> None:
    assert _rules(_diff("a.py", ["def f():", "    raise NotImplementedError"])) == ["stub"]
    assert _rules(_diff("a.rs", ["    todo!()"])) == ["stub"]
    assert _rules(_diff("a.py", ["def f():", "    pass  # stub"])) == ["stub"]
    assert _rules(_diff("a.py", ["def f():", "    # stub", "    ..."])) == ["stub"]


def test_abstract_not_implemented_and_plain_pass_are_quiet() -> None:
    abstract = [
        "    @abstractmethod",
        "    def run(self) -> None:",
        "        raise NotImplementedError",
    ]
    assert _rules(_diff("a.py", abstract)) == []
    assert _rules(_diff("a.py", ["    def run(self) -> None:", "        raise NotImplementedError"],
                        ctx=["    @abc.abstractmethod"])) == []  # fmt: skip
    assert _rules(_diff("a.py", ["except KeyError:", "    pass"])) == []
    assert _rules(_diff("a.py", ["class E(Exception): ..."])) == []


# 4 self-referential evidence
def test_self_referential_evidence_fires() -> None:
    f = report_findings(_report(summary="Done; it works as expected."))
    assert [(x.rule, x.path) for x in f] == [
        ("self-referential-evidence", "worker_report.json:summary")
    ]
    f = report_findings(_report(reviewer_would_flag="Manually verified in a shell"))
    assert f[0].path == "worker_report.json:self_check.reviewer_would_flag"


def test_a_report_that_names_its_evidence_is_quiet() -> None:
    assert report_findings(_report(summary="Added the guard; test_refuses_x covers it.")) == []


# 5 deleted guard
def test_a_removed_guard_without_a_negative_test_fires() -> None:
    d = _diff("vigild/x.py", ["pass_through = True"], removed=["    if path not in ALLOWED_PATHS:"])
    [f] = check(d)
    assert (f.rule, f.path, f.line) == ("guard-removed", "vigild/x.py", 10)
    assert _rules(_diff("tests/test_x.py", [], removed=["def test_refuses_bad_path():"])) == [
        "guard-removed"
    ]
    assert _rules(_diff("a.py", [], removed=["    raise ValueError('bad')"])) == ["guard-removed"]


def test_a_guard_with_a_replacement_or_a_new_negative_test_is_quiet() -> None:
    swapped = _diff("tests/test_x.py", ["def test_refuses_y():"], removed=["def test_refuses_x():"])
    assert _rules(swapped) == []
    edited = _diff(
        "a.py", ["    if p not in ALLOWED_PATHS or q:"], removed=["    if p not in ALLOWED_PATHS:"]
    )
    assert _rules(edited) == []
    both = {**_diff("a.py", [], removed=["    validate(x)"]),
            **_diff("tests/test_a.py", ["    with pytest.raises(ValueError):"])}  # fmt: skip
    assert _rules(both) == []
    assert _rules(_diff("a.py", [], removed=["x = 1"])) == []


# fix round 1: false positives
def test_js_skip_and_only_outside_test_files_are_quiet() -> None:
    assert _rules(_diff("lib.js", ["const rest = cursor.skip(10);"])) == []
    assert _rules(_diff("lib.ts", ["opt.only(1)"])) == []
    assert _rules(_diff("a.test.ts", ["cursor.skip(10)"])) == []


def test_a_comment_marker_inside_a_string_is_not_a_comment() -> None:
    assert _rules(_diff("a.py", ['msg = "see # TODO list"'])) == []
    assert _rules(_diff("a.js", ['u = "http://x.io/TODO"'])) == []
    assert _rules(_diff("a.py", ['    """Flags a `# TODO` comment."""'])) == []
    assert _rules(_diff("a.py", ["# TODO(alice) tidy"])) == ["todo-without-issue"]
    assert _rules(_diff("a.py", ["x = 'it''s'  # TODO tidy"])) == ["todo-without-issue"]


def test_not_implemented_in_protocols_abcs_and_test_doubles_is_quiet() -> None:
    body = ["    def run(self) -> None:", "        raise NotImplementedError"]
    assert _rules(_diff("a.py", body, ctx=["class P(Protocol):"])) == []
    assert _rules(_diff("a.py", body, ctx=["class P(Base, metaclass=ABCMeta):"])) == []
    assert _rules(_diff("a.py", body, ctx=["    @overload"])) == []
    assert _rules(_diff("tests/test_fake.py", body)) == []
    assert _rules(_diff("a.py", body)) == ["stub"]


def test_not_implemented_reads_the_full_new_file_when_given() -> None:
    d = _diff("a.py", ["        raise NotImplementedError"])
    src = (
        "class P(Protocol):\n"
        + "\n" * 18
        + "    def run(self) -> None:\n"
        + "        raise NotImplementedError\n"
    )
    assert d["a.py"] and check(d) != []
    assert (
        check({"a.py": "@@ -1,0 +21,1 @@\n+        raise NotImplementedError\n"}, lambda p: src)
        == []
    )
    assert [f.rule for f in check(
        {"a.py": "@@ -1,0 +21,1 @@\n+        raise NotImplementedError\n"},
        lambda p: src.replace("Protocol", "Base"))] == ["stub"]  # fmt: skip


def test_a_deleted_or_moved_guard_is_quiet() -> None:
    gone = {"a.py": "--- a/a.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-raise ValueError('x')\n"}
    assert _rules(gone) == []
    moved = {**_diff("a.py", [], removed=["validate(x)"]), **_diff("b.py", ["  validate(x)"])}
    assert _rules(moved) == []
    assert _rules(_diff("a.py", ["raise TypeError"], removed=["raise ValueError"])) == []
    assert _rules(_diff("a.py", ["X = 1"], removed=["ALLOWED = 1"])) == []


def test_a_not_found_test_does_not_hide_a_removed_guard() -> None:
    both = {**_diff("a.py", [], removed=["    validate(x)"]),
            **_diff("tests/test_a.py", ["def test_not_found():", "def test_fail_soft():"])}  # fmt: skip
    assert _rules(both) == ["guard-removed"]


def test_stubbed_and_reasonable_are_not_markers() -> None:
    assert _rules(_diff("a.py", ["except E:", "    pass  # stubbed out"])) == []
    assert _rules(_diff("t.py", ["@pytest.mark.skipif(not reasonable)"])) == ["skip-without-reason"]


def test_self_referential_evidence_ignores_questions_and_named_tests() -> None:
    r = _report(summary="Works as expected, see test_refuses_x.")
    assert report_findings(r) == []
    r = _report(summary="ok")
    r2 = r.model_copy(update={"open_questions": ["is it manually verified?"]})
    assert report_findings(r2) == []

"""A dev-image validation record names its failing tests (#190): the tail keeps the
summary and the FAILED lines, never the base64 trailer, and doctor names the failures."""

from __future__ import annotations

import base64
import json
from typing import Any

from vigild.devimage import TAIL, dev_image_note, failed_tests, smart_tail
from vigild.verifier import RunResult

IDS = [
    "tests/test_a.py::test_one",
    "tests/test_b.py::TestX::test_two",
    "tests/test_c.py::test_three[param]",
]


def big_output() -> str:
    parts = ["." * 80 + f" [{i}%]\n" for i in range(1500)]  # ~120 KB of dots
    mid = ["=== FAILURES ===\n"]
    for i in IDS:
        name = i.split("::")[-1]
        mid.append(
            f"____ {name} ____\n\n    def f():\n>       assert 1 == 2\nE       assert 1 == 2\nE       +1\n"
        )
    parts[700:700] = mid
    parts.append("\n".join(f"FAILED {i} - assert 1 == 2" for i in IDS) + "\n")
    parts.append("=== 3 failed, 4000 passed in 61.2s ===\n")
    blob = base64.b64encode(b"<testsuites>" + b"x" * 60000 + b"</testsuites>").decode()
    parts.append("VIGIL-REPORT-abc BEGIN\nVIGIL-REPORT-abc pytest.xml\n" + blob + "\n")
    return "".join(parts)


def test_smart_tail_keeps_summary_and_failures_and_drops_base64() -> None:
    out = big_output()
    assert len(out) > 190_000
    tail = smart_tail(out)
    assert len(tail) <= TAIL
    assert "=== 3 failed, 4000 passed in 61.2s ===" in tail
    for i in IDS:
        assert f"FAILED {i}" in tail
    assert tail.count("E       assert 1 == 2") == 3
    assert "VIGIL-REPORT" not in tail and "eHh4eHh4" not in tail


def test_failed_tests_come_from_the_regex_without_a_report() -> None:
    assert failed_tests(RunResult(1, big_output())) == IDS


def test_failed_tests_prefer_the_junit_report() -> None:
    xml = (
        b'<testsuites><testsuite><testcase classname="tests.test_a" name="test_x"/>'
        b'<testcase classname="tests.test_a" name="test_bad"><failure message="m"/></testcase>'
        b'<testcase classname="tests.test_b" name="test_err"><error message="m"/></testcase>'
        b"</testsuite></testsuites>"
    )
    r = RunResult(1, "FAILED other::id\n", reports={"pytest.xml": xml})
    assert failed_tests(r) == ["tests.test_a::test_bad", "tests.test_b::test_err"]


def test_failed_tests_are_capped_at_fifty() -> None:
    out = "".join(f"FAILED t.py::t{i}\n" for i in range(80))
    assert len(failed_tests(RunResult(1, out))) == 50


def row(output: str, ok: int = 0) -> dict[str, Any]:
    return {"ok": ok, "image": "img", "stage": "validate", "output": output}


def test_doctor_names_up_to_three_failures_and_counts_the_rest() -> None:
    ids = [f"t.py::t{i}" for i in range(5)]
    body = {"suites": {"unit": {"outcome": "fail", "failed_tests": ids}}}
    note = dev_image_note(row(json.dumps(body)))
    assert note == "img failed its validate  (unit failed: t.py::t0, t.py::t1, t.py::t2 +2 more)"


def test_an_old_record_without_names_still_renders() -> None:
    body = {"suites": {"unit": {"outcome": "fail", "exit": 1, "tail": "x"}}}
    assert dev_image_note(row(json.dumps(body))) == "img failed its validate"
    assert dev_image_note(row("not json")) == "img failed its validate"
    assert dev_image_note(row(json.dumps({"build": "boom"}))) == "img failed its validate"

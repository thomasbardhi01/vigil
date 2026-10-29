"""#105 (ADR-0006 C): a review finding carries evidence {kind, ref} and a confidence."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from vigild.contract.models import Finding

BASE: dict[str, Any] = {"severity": "medium", "file": "a.py", "line": 3, "claim": "c", "fix": "f"}
GOOD: dict[str, Any] = {
    **BASE,
    "evidence": {"kind": "diff_line", "ref": "a.py:3"},
    "confidence": 0.8,
}


def _refused(data: dict[str, Any], word: str) -> None:
    with pytest.raises(ValidationError) as e:
        Finding.model_validate(data)
    assert word in str(e.value)


def test_a_finding_with_evidence_and_confidence_parses() -> None:
    f = Finding.model_validate(GOOD)
    assert f.evidence.kind == "diff_line" and f.confidence == 0.8


@pytest.mark.parametrize(
    "ev",
    [
        {"kind": "test", "ref": "tests/test_a.py::test_x"},
        {"kind": "spec_criterion", "ref": "AC3"},
        {"kind": "runtime_log", "ref": "log-2"},
        {"kind": "diff_line", "ref": "a.py:12-20"},
        {"kind": "diff_line", "ref": "a.py:L12"},
    ],
)
def test_each_kind_parses(ev: dict[str, str]) -> None:
    Finding.model_validate({**GOOD, "evidence": ev})


def test_a_finding_missing_evidence_is_refused_naming_the_field() -> None:
    _refused({k: v for k, v in GOOD.items() if k != "evidence"}, "evidence")


def test_a_finding_missing_confidence_is_refused_naming_the_field() -> None:
    _refused({k: v for k, v in GOOD.items() if k != "confidence"}, "confidence")


@pytest.mark.parametrize(
    "ev",
    [
        {"kind": "diff_line", "ref": "a.py"},
        {"kind": "diff_line", "ref": "a.py:x"},
        {"kind": "spec_criterion", "ref": "criterion one"},
        {"kind": "test", "ref": ""},
        {"kind": "runtime_log", "ref": "   "},
        {"kind": "guess", "ref": "x"},
    ],
)
def test_an_ill_formed_locator_is_refused(ev: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        Finding.model_validate({**GOOD, "evidence": ev})


def test_a_diff_line_without_a_line_number_names_the_locator() -> None:
    _refused({**GOOD, "evidence": {"kind": "diff_line", "ref": "a.py"}}, "path:line")


@pytest.mark.parametrize("c", [-0.1, 1.01, 7])
def test_a_confidence_outside_0_to_1_is_refused(c: float) -> None:
    _refused({**GOOD, "confidence": c}, "confidence")


@pytest.mark.parametrize("ref", ["AC-3", "ac3", "AC 3", "AC3"])
def test_an_ac_ref_is_normalised(ref: str) -> None:
    f = Finding.model_validate({**GOOD, "evidence": {"kind": "spec_criterion", "ref": ref}})
    assert f.evidence.ref == "AC3"


def test_an_empty_ref_is_refused() -> None:
    with pytest.raises(ValidationError):
        Finding.model_validate({**GOOD, "evidence": {"kind": "spec_criterion", "ref": ""}})


def test_a_stored_finding_without_evidence_or_confidence_parses() -> None:
    from vigild.contract.models import StoredFinding

    f = StoredFinding.model_validate(BASE)
    assert f.evidence is None and f.confidence is None


def test_a_new_review_without_evidence_is_still_refused() -> None:
    from vigild.contract.models import CHECKLIST, ReviewOutput

    doc = {"verdict": "changes", "findings": [BASE], "checklist": {c: True for c in CHECKLIST}}
    with pytest.raises(ValidationError) as e:
        ReviewOutput.model_validate(doc)
    assert "evidence" in str(e.value)

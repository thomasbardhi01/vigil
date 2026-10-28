"""ci.yml must never skip a required check by event action: a skipped lint/types/test
run on the same head reads as passing to the ruleset. The `edited` trigger belongs
to image-key.yml alone."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WF = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _load(name: str) -> dict[str, Any]:
    doc = yaml.safe_load((WF / name).read_text())
    doc["on"] = doc.pop(True, doc.get("on"))  # YAML reads a bare `on` as True
    return dict(doc)


def test_ci_yml_has_no_edited_type_and_no_job_is_skipped_by_event_action() -> None:
    ci = _load("ci.yml")
    assert "edited" not in (ci["on"].get("pull_request") or {}).get("types", [])
    for name, job in ci["jobs"].items():
        assert "github.event.action" not in str(job.get("if", "")), name
    assert "event.action" not in str(ci.get("concurrency", ""))


def test_image_key_has_its_own_workflow() -> None:
    wf = _load("image-key.yml")
    assert wf["on"]["pull_request"]["types"] == ["opened", "synchronize", "reopened", "edited"]
    assert wf["concurrency"]["group"] == "image-key-${{ github.ref }}"
    assert wf["permissions"] == {"contents": "read"}
    job = wf["jobs"]["image-key"]
    assert job["permissions"] == {"contents": "read", "pull-requests": "write"}
    assert job["timeout-minutes"] == 45
    assert "image-key" not in _load("ci.yml")["jobs"]

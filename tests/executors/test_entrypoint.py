"""The executor harness's own pieces that run without a container (item 13,
blocker 3): redaction, and writing its record past a planted symlink."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest

from vigild.jobs.runner import redact as vigild_redact

ROOT = Path(__file__).resolve().parents[2]


def _entrypoint() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "entrypoint", ROOT / "images" / "claude-executor" / "entrypoint.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TOKEN = "vgw_" + "A" * 43


@pytest.mark.parametrize("redact", [lambda v: _entrypoint().redact(v, TOKEN), vigild_redact])
def test_tokens_are_redacted_from_events(redact: object) -> None:
    event = {
        "type": "tool_call",
        "data": {
            "input": {"command": f"echo $ANTHROPIC_AUTH_TOKEN # {TOKEN}"},
            "content": ["sk-ant-api03-abcdefghijkl", "ghs_abcdefghijklmnop", "ok"],
        },
    }
    out = redact(event)  # type: ignore[operator]
    flat = str(out)
    assert TOKEN not in flat and "sk-ant-api03" not in flat and "ghs_abcdef" not in flat
    assert "ok" in flat and "[redacted]" in flat


def test_the_harness_record_replaces_a_planted_symlink(tmp_path: Path) -> None:
    ep = _entrypoint()
    target = tmp_path / "elsewhere.txt"
    target.write_text("untouched")
    out = tmp_path / "out"
    out.mkdir()
    os.symlink(target, out / "harness_tests.json")
    ep.OUT = out
    ep.write_out("harness_tests.json", b"{}")
    assert target.read_text() == "untouched"
    assert not (out / "harness_tests.json").is_symlink()
    assert (out / "harness_tests.json").read_text() == "{}"


def test_unknown_outcome_is_named_for_vigild_to_reject() -> None:
    ep = _entrypoint()
    assert ep.outcome(127) == "unknown" and ep.outcome(0) == "pass" and ep.outcome(1) == "fail"

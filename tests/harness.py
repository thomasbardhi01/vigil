"""What the executor harness does at the end of a session, for tests that
stand in for the container: commit leftovers, write the harness record and
the result bundle into the session's out dir."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.conftest import git


def finish_session(
    clone: Path,
    out_dir: Path,
    *,
    branch: str,
    base_sha: str,
    harness: dict[str, Any] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    if git(clone, "status", "--porcelain"):
        git(clone, "add", "-A")
        git(clone, "commit", "-q", "-m", "harness: leftovers")
    if harness is not None:
        (out_dir / "harness_tests.json").write_text(json.dumps({**harness, "provenance": "human"}))
    git(clone, "bundle", "create", "-q", str(out_dir / "result.bundle"), f"refs/heads/{branch}",
        f"^{base_sha}")  # fmt: skip

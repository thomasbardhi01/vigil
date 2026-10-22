"""The repo checks CI runs: the feature map and CLAUDE.md."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str) -> ModuleType:
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace("-", "_").removesuffix(".py"), path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fm = _load("check-feature-map.py")
cm = _load("check-claude-md.py")

MAP = """
| Feature | Phase | What it does | Entry points | Core code | Guardrails | Tests | Status |
|---|---|---|---|---|---|---|---|
| A | 1 | x | `GET /api/things/{id}` | `pkg/a.py`, `pkg/{b,c}.py` | — | `tests/test_a.py` | shipped |
| B | 2 | y | `POST /api/later` | `pkg/missing.py` | — | — | planned (phase 2) |
"""


def _tree(tmp: Path, files: list[str], source: str = "") -> Path:
    (tmp / "docs").mkdir()
    (tmp / "docs" / "feature-map.md").write_text(MAP)
    for f in files:
        p = tmp / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(source if f.endswith("api.py") else "")
    return tmp


def test_shipped_row_paths_must_exist(tmp_path: Path) -> None:
    root = _tree(tmp_path, ["pkg/a.py", "pkg/b.py", "tests/test_a.py"])
    errors = fm.check(root, code_dirs=["pkg"])
    assert any("pkg/c.py" in e for e in errors)
    # A planned row may name paths that don't exist yet.
    assert not any("pkg/missing.py" in e for e in errors)


def test_clean_tree_passes(tmp_path: Path) -> None:
    src = '@router.get("/api/things/{thing_id}")\ndef f(): ...\n'
    root = _tree(
        tmp_path, ["pkg/a.py", "pkg/b.py", "pkg/c.py", "tests/test_a.py", "pkg/api.py"], src
    )
    assert fm.check(root, code_dirs=["pkg"]) == []


def test_route_in_code_but_in_no_row_fails(tmp_path: Path) -> None:
    src = '@router.post("/api/secret-door")\ndef f(): ...\n'
    root = _tree(
        tmp_path, ["pkg/a.py", "pkg/b.py", "pkg/c.py", "tests/test_a.py", "pkg/api.py"], src
    )
    errors = fm.check(root, code_dirs=["pkg"])
    assert errors == ["route POST /api/secret-door is in code but in no feature-map row"]


def test_real_repo_feature_map_is_clean() -> None:
    assert fm.check(ROOT) == []


def test_claude_md_limits(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("x\n" * 201)
    (tmp_path / "AGENTS.md").symlink_to("CLAUDE.md")
    assert any("201 lines" in e for e in cm.check(tmp_path))
    (tmp_path / "CLAUDE.md").write_text("x\n" * 10)
    assert cm.check(tmp_path) == []
    (tmp_path / "AGENTS.md").unlink()
    (tmp_path / "AGENTS.md").write_text("copy")
    assert any("symlink" in e for e in cm.check(tmp_path))


def test_real_repo_claude_md_is_clean() -> None:
    assert cm.check(ROOT) == []

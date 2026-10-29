"""Related tests by the reverse import graph (#107, ADR-0005 work)."""

from __future__ import annotations

from pathlib import Path

from vigild.packets.assemble import _context_pack
from vigild.packets.related_tests import BLIND_SPOTS, read_py, related_tests

FILES = {
    "pkg/__init__.py": "",
    "pkg/mod.py": "X = 1\n",
    "pkg/mid.py": "from pkg import mod\n",
    "pkg/top.py": "import pkg.mid\n",
    "pkg/far.py": "from pkg.top import *\n",
    "pkg/sub/__init__.py": "",
    "pkg/sub/rel.py": "from ..mod import X\n",
    "pkg/sub/sib.py": "from . import rel\n",
    "pkg/lonely.py": "Z = 1\n",
    "tests/test_direct.py": "import pkg.mod\n",
    "tests/test_mid.py": "from pkg.mid import something\n",
    "tests/test_far.py": "import pkg.far\n",
    "tests/test_pkg.py": "import pkg\n",
    "tests/test_rel.py": "from pkg.sub import sib\n",
    "tests/test_other.py": "import pkg.lonely\n",
}


def test_a_direct_import_is_related() -> None:
    assert "tests/test_direct.py" in related_tests(FILES, ["pkg/mod.py"])


def test_transitive_within_the_depth_bound_only() -> None:
    got = related_tests(FILES, ["pkg/mod.py"], depth=3)
    assert "tests/test_mid.py" in got  # mod <- mid <- test_mid
    assert "tests/test_far.py" not in got  # mod <- mid <- top <- far <- test_far is depth 4
    assert "tests/test_far.py" in related_tests(FILES, ["pkg/mod.py"], depth=4)


def test_an_init_change_relates_every_test_importing_the_package() -> None:
    got = related_tests(FILES, ["pkg/__init__.py"], depth=1)
    assert {"tests/test_pkg.py", "tests/test_direct.py", "tests/test_mid.py"} <= set(got)


def test_a_relative_import_resolves() -> None:
    assert "tests/test_rel.py" in related_tests(FILES, ["pkg/sub/rel.py"])
    assert "pkg/sub/sib.py" not in related_tests(FILES, ["pkg/mod.py"])  # not a test


def test_an_unrelated_test_is_not_returned() -> None:
    got = related_tests(FILES, ["pkg/mod.py"])
    assert "tests/test_other.py" not in got


def test_nearer_tests_come_first() -> None:
    got = related_tests(FILES, ["pkg/mod.py"])
    assert got.index("tests/test_direct.py") < got.index("tests/test_mid.py")


def test_a_non_python_file_relates_nothing() -> None:
    assert related_tests(FILES, ["web/app.ts"]) == []


def test_a_syntax_error_file_is_skipped() -> None:
    files = {**FILES, "pkg/bad.py": "def (:\n"}
    assert "tests/test_direct.py" in related_tests(files, ["pkg/mod.py"])


def test_the_packet_carries_the_blind_spots(tmp_path: Path) -> None:
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    pack, _ = _context_pack(tmp_path, ["pkg/mod.py"], 100_000, None)
    assert "tests/test_direct.py (related test)" in pack
    assert BLIND_SPOTS in pack
    pack, _ = _context_pack(tmp_path, ["pkg/lonely.py", "tests/test_other.py"], 100_000, None)
    assert "tests/test_other.py (related test)" not in pack  # it is in scope already


def test_this_repo_budget_has_direct_and_indirect_tests() -> None:
    root = Path(__file__).resolve().parents[2]
    paths = [
        str(p.relative_to(root))
        for d in ("vigild", "cli", "tests")
        for p in (root / d).rglob("*.py")
    ]
    files = {p: t for p in paths if (t := read_py(root, p)) is not None}
    got = related_tests(files, ["vigild/budget.py"])
    assert "tests/test_budget.py" in got
    direct = {
        p for p in got if "import vigild.budget" in files[p] or "vigild.budget import" in files[p]
    }
    assert set(got) - direct  # at least one test reaches budget through another module

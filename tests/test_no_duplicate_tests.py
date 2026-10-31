"""#199: a test module never defines the same test twice. The second definition silently
replaces the first, which then never runs. Thirty test modules switch ruff's F811 off for
the whole file (they re-import pytest fixtures), so this guard checks test names itself."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def _duplicates(source: str) -> list[str]:
    tree = ast.parse(source)
    names = [
        n.name
        for n in tree.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name.startswith("test_")
    ]
    names += [
        f"{c.name}.{n.name}"
        for c in tree.body
        if isinstance(c, ast.ClassDef)
        for n in c.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name.startswith("test_")
    ]
    return sorted(name for name, count in Counter(names).items() if count > 1)


def test_the_guard_finds_a_redefined_test() -> None:
    src = "def test_a():\n    pass\n\ndef test_b():\n    pass\n\ndef test_a(x):\n    pass\n"
    assert _duplicates(src) == ["test_a"]


def test_no_test_module_defines_a_test_twice() -> None:
    found = {
        str(p.relative_to(TESTS)): dups
        for p in sorted(TESTS.rglob("test_*.py"))
        if (dups := _duplicates(p.read_text()))
    }
    assert found == {}, f"tests defined twice (the first never runs): {found}"

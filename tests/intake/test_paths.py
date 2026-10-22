"""Glob semantics shared with guard and route."""

from __future__ import annotations

import pytest

from vigild.intake.paths import matches, matches_any


@pytest.mark.parametrize(
    "path,glob,expected",
    [
        ("src/billing/charge.py", "src/billing/**", True),
        ("server/src/billing/x/y.ts", "src/billing/**", True),  # tail match
        ("src/billingx/a.py", "src/billing/**", False),
        ("a/payments/b.py", "**/payments/**", True),
        ("payments/b.py", "**/payments/**", True),  # leading **/ may be empty
        ("deep/dir/.env", ".env", True),  # no slash: basename anywhere
        ("deep/dir/.ENV", ".env", True),  # case-insensitive
        ("deep/dir/x.env.local", "*.env.*", True),
        ("docs/a.md", "*.py", False),
        ("fly.toml", "fly.toml", True),
    ],
)
def test_glob_semantics(path: str, glob: str, expected: bool) -> None:
    assert matches(path, glob) is expected


def test_matches_any() -> None:
    assert matches_any("src/auth/login.py", ["src/billing/**", "src/auth/**"])
    assert not matches_any("docs/x.md", ["src/billing/**"])

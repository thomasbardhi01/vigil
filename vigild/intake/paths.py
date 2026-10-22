"""Glob semantics shared with guard and route (claude-mods):
- a glob without `/` matches the basename anywhere;
- a glob with `/` matches the path's tail;
- matching is case-insensitive.
"""

from __future__ import annotations

from collections.abc import Iterable
from fnmatch import fnmatchcase


def matches(path: str, glob: str) -> bool:
    p = path.strip().removeprefix("./").lower()
    g = glob.strip().lower()
    if "/" not in g:
        return fnmatchcase(p.rsplit("/", 1)[-1], g)
    candidates = [g]
    while candidates[-1].startswith("**/"):
        candidates.append(candidates[-1][3:])  # a leading **/ may match nothing
    return any(fnmatchcase(p, c) or fnmatchcase(p, "*/" + c) for c in candidates)


def matches_any(path: str, globs: Iterable[str]) -> bool:
    return any(matches(path, g) for g in globs)

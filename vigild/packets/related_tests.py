"""Related tests by the reverse import graph (#107, ADR-0005 work).

Replaces the `tests/test_<stem>*.py` name heuristic for Python files. With stdlib
`ast` only, the repo's `.py` files are parsed (never run) into an import graph;
the tests that import a changed file directly, or through up to `DEPTH` hops of
other modules, are its related tests, nearest first. Importing `a.b.c` also
depends on the `__init__.py` of `a` and `a.b`, and `from p import m` on `p.m`
when that is a module, so an `__init__.py` is related to every importer of its
package. Files that don't parse are skipped. Non-Python files keep the name
heuristic (the callers' fallback)."""

from __future__ import annotations

import ast
import re
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path

from vigild.gitsafe import GitError, git
from vigild.safefile import safe_read_text

DEPTH = 3
BLIND_SPOTS = (
    "Related tests come from static imports only. They miss dynamic imports "
    "(importlib, __import__, plugins), pytest fixtures and conftest.py, and code "
    "run in subprocesses, so a test can touch these files and not be listed."
)
_TEST_FILE = re.compile(r"(test_.*\.py|.*_test\.py|.*\.(test|spec)\.\w+)$")
_cache: dict[str, dict[str, set[str]]] = {}


def is_test_file(name: str) -> bool:
    return bool(_TEST_FILE.match(name))


def read_py(root: Path, rel: str) -> str | None:
    try:
        return safe_read_text(root, root / rel)
    except OSError:
        return None


def load_py(root: Path) -> tuple[dict[str, str], str | None]:
    """The repo's tracked `.py` files as text (read safely, never run) and the
    tree id that keys the cache; outside a repo, every `.py` file and no id."""
    try:
        listed = git(root, "ls-files", "-z", raw=True).split("\0")
        paths = [p for p in listed if p.endswith(".py")]
        tree: str | None = git(root, "rev-parse", "HEAD^{tree}").strip()
    except GitError, OSError:
        paths = [str(p.relative_to(root)) for p in root.rglob("*.py") if ".git" not in p.parts]
        tree = None
    return {p: t for p in paths if (t := read_py(root, p)) is not None}, tree


def _module(path: str) -> str:
    parts = path[:-3].split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _imports(path: str, text: str, modules: Mapping[str, str]) -> set[str]:
    """The repo files `text` (the source of `path`) imports."""
    try:
        tree = ast.parse(text)
    except SyntaxError, ValueError:
        return set()
    pkg = _module(path) if path.endswith("__init__.py") else _module(path).rpartition(".")[0]
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = pkg.split(".") if pkg else []
                up = up[: len(up) - (node.level - 1)] if node.level > 1 else up
                if node.level - 1 > len(pkg.split(".") if pkg else []):
                    continue
                base = ".".join([*up, *([base] if base else [])])
            names.append(base)
            names += [f"{base}.{a.name}" if base else a.name for a in node.names]
    deps: set[str] = set()
    for name in names:
        parts = name.split(".")
        for i in range(1, len(parts) + 1):  # the module and every package above it
            if (f := modules.get(".".join(parts[:i]))) is not None:
                deps.add(f)
    deps.discard(path)
    return deps


def _graph(files: Mapping[str, str]) -> dict[str, set[str]]:
    """file -> the files that import it."""
    py = {p: t for p, t in files.items() if p.endswith(".py")}
    modules = {_module(p): p for p in py}
    rev: dict[str, set[str]] = {}
    for path, text in py.items():
        for dep in _imports(path, text, modules):
            rev.setdefault(dep, set()).add(path)
    return rev


def related_tests(
    files: Mapping[str, str],
    changed: Sequence[str],
    depth: int = DEPTH,
    tree: str | None = None,
) -> list[str]:
    """The test files that reach any of `changed` within `depth` imports, nearest
    first. `files` maps each repo `.py` path to its text; `tree` (the repo tree id,
    when the caller has one) keys a cache of the graph."""
    rev = _cache.get(tree) if tree else None
    if rev is None:
        rev = _graph(files)
        if tree:
            _cache.clear()  # one tree at a time keeps it small
            _cache[tree] = rev
    seen = {c: 0 for c in changed if c.endswith(".py")}
    queue = deque(seen)
    while queue:
        cur = queue.popleft()
        if seen[cur] >= depth:
            continue
        for nxt in sorted(rev.get(cur, ())):
            if nxt not in seen:
                seen[nxt] = seen[cur] + 1
                queue.append(nxt)
    tests = [p for p in seen if p not in changed and is_test_file(p.rsplit("/", 1)[-1])]
    return sorted(tests, key=lambda p: (seen[p], p))

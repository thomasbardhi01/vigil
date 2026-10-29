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
import hashlib
import re
from collections import deque
from collections.abc import Mapping, Sequence
from fnmatch import fnmatchcase
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


def load_py(root: Path) -> dict[str, str]:
    """The repo's tracked `.py` files as text (read safely, never run); outside a
    repo, every `.py` file."""
    try:
        listed = git(root, "ls-files", "-z", raw=True).split("\0")
        paths = [p for p in listed if p.endswith(".py")]
    except GitError, OSError:
        paths = [str(p.relative_to(root)) for p in root.rglob("*.py") if ".git" not in p.parts]
    return {p: t for p in paths if (t := read_py(root, p)) is not None}


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
    deps: set[str] = set()
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
            # `from pkg import x` with `x` a submodule links x, not pkg/__init__.py
            # (else a change to any module reaches every importer of the package).
            # Only the package root is resolved: `from ... import y` beyond it,
            # or a relative import above the root, silently links nothing.
            subs = [f"{base}.{a.name}" if base else a.name for a in node.names]
            rest = [n for n in subs if n not in modules]
            if rest or not node.names:
                names.append(base)
            deps.update(modules[n] for n in subs if n in modules)
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


def _digest(files: Mapping[str, str]) -> str:
    h = hashlib.sha256()
    for path in sorted(files):
        h.update(f"{path}\0{len(files[path])}\0".encode() + files[path].encode(errors="replace"))
    return h.hexdigest()


def _name_match(test: str, changed: str) -> bool:
    """The old heuristic: `test_<stem>*.py` or `<stem>_test.py`."""
    stem = changed.rsplit("/", 1)[-1][:-3]
    base = test.rsplit("/", 1)[-1]
    return stem != "__init__" and (
        fnmatchcase(base, f"test_{stem}*.py") or base == f"{stem}_test.py"
    )


def _reach(rev: Mapping[str, set[str]], start: str, depth: int) -> dict[str, int]:
    seen = {start: 0}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        if seen[cur] >= depth:
            continue
        for nxt in sorted(rev.get(cur, ())):
            if nxt not in seen:
                seen[nxt] = seen[cur] + 1
                queue.append(nxt)
    return seen


def related_tests(
    files: Mapping[str, str],
    changed: Sequence[str],
    depth: int = DEPTH,
) -> list[str]:
    """The test files that reach any of `changed` within `depth` imports. `files`
    maps each repo `.py` path to its text (a digest of it keys the graph cache).
    Order: tests matching the old `test_<stem>*` name heuristic first, by path;
    then by how many changed files they reach (more first), hop depth (nearer
    first) and path."""
    key = _digest(files)
    rev = _cache.get(key)
    if rev is None:
        rev = _graph(files)
        _cache.clear()  # one graph at a time keeps it small
        _cache[key] = rev
    pys = [c for c in dict.fromkeys(changed) if c.endswith(".py")]
    count: dict[str, int] = {}
    near: dict[str, int] = {}
    for c in pys:
        for p, d in _reach(rev, c, depth).items():
            count[p] = count.get(p, 0) + 1
            near[p] = min(near.get(p, d), d)
    named = {
        p
        for p in files
        if is_test_file(p.rsplit("/", 1)[-1]) and any(_name_match(p, c) for c in pys)
    }
    tests = {p for p in count if is_test_file(p.rsplit("/", 1)[-1])} | named
    tests -= set(changed)
    return sorted(
        tests,
        key=lambda p: (0, 0, 0, p) if p in named else (1, -count.get(p, 0), near.get(p, 0), p),
    )

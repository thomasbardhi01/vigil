"""Per-row docs: one file per feature and per architecture decision (#96).

The source of truth for a row is `docs/features/<slug>.md` (feature map) or
`docs/decisions/arch/<slug>.md` (architecture decision table): YAML front
matter holds the table's columns, the body holds the long-text column. Rows
may still sit in the tables of `docs/feature-map.md` / `docs/architecture.md`;
every reader goes through `merged_rows`, which accepts both and refuses a slug
defined twice. The generated table is never committed
(`scripts/gen-docs-tables.py` renders it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from vigild.safefile import safe_read_bytes

SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
CELL_SPLIT = re.compile(r"(?<!\\)\|")
STATUS_PREFIXES = (
    "shipped",
    "planned",
    "proposed",
    "accepted",
    "partial",
    "disabled",
    "blocked",
)


@dataclass(frozen=True)
class Kind:
    dir: str
    table_doc: str
    # (front-matter key, table header) in column order; key None is the body.
    columns: tuple[tuple[str | None, str], ...]
    marker: str  # the header that tells this kind's table from other tables


KINDS: dict[str, Kind] = {
    "features": Kind(
        "docs/features",
        "docs/feature-map.md",
        (
            ("id", "ID"),
            ("feature", "Feature"),
            ("phase", "Phase"),
            (None, "What it does"),
            ("entry_points", "Entry points"),
            ("core_code", "Core code"),
            ("guardrails", "Guardrails"),
            ("tests", "Tests"),
            ("status", "Status"),
        ),
        "Feature",
    ),
    "decisions": Kind(
        "docs/decisions/arch",
        "docs/architecture.md",
        (("id", "ID"), ("choice", "Choice"), ("picked", "Picked"), (None, "Why")),
        "Choice",
    ),
}


class DuplicateSlug(ValueError):
    pass


def headers(kind: str) -> list[str]:
    return [h for _, h in KINDS[kind].columns]


def table_rows(text: str, kind: str) -> list[dict[str, str]]:
    """Header-keyed rows of every table in `text` that is this kind's table."""
    want = headers(kind)
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in text.splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = [c.strip() for c in CELL_SPLIT.split(line.strip().strip("|"))]
        if header is None:
            header = cells
            continue
        if all(set(c) <= {"-", ":", " "} for c in cells):
            continue
        if header[:1] == ["ID"] and KINDS[kind].marker in header:
            row = dict(zip(header, cells, strict=False))
            rows.append({h: row.get(h, "") for h in want})
    return rows


def _read(root: Path, path: Path) -> str:
    """A repo file's text, refusing symlinks and oversize files (a session may
    have written the checkout)."""
    return safe_read_bytes(root, path).decode()


def parse_row_file(
    root: Path, path: Path, kind: str, rel: str
) -> tuple[dict[str, str] | None, list[str]]:
    """The row a file holds (header-keyed) and its problems."""
    try:
        text = _read(root, path)
    except (OSError, UnicodeDecodeError) as e:
        return None, [f"{rel}: unreadable ({e})"]
    m = re.match(r"---\n(.*?)\n---\n(.*)\Z", text, re.DOTALL)
    if not m:
        return None, [f"{rel}: no YAML front matter (a `---` block at the top)"]
    try:
        meta: Any = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        return None, [f"{rel}: front matter is not valid YAML ({e})"]
    if not isinstance(meta, dict):
        return None, [f"{rel}: front matter is not a mapping"]
    errors: list[str] = []
    row: dict[str, str] = {}
    for key, header in KINDS[kind].columns:
        if key is None:
            body = " ".join(m.group(2).split()).replace("|", "\\|")
            if not body:
                errors.append(f"{rel}: empty body (the `{header}` column)")
            row[header] = body
        elif key not in meta or meta[key] is None or str(meta[key]).strip() == "":
            errors.append(f"{rel}: missing column `{key}`")
        else:
            row[header] = " ".join(str(meta[key]).split()).replace("|", "\\|")
    extra = set(meta) - {k for k, _ in KINDS[kind].columns if k}
    if extra:
        errors.append(f"{rel}: unknown front-matter keys {sorted(extra)}")
    slug = row.get("ID", "")
    if "ID" in row and not SLUG.match(slug):
        errors.append(f"{rel}: slug `{slug}` is not kebab-case")
    elif "ID" in row and slug != path.stem:
        errors.append(f"{rel}: slug `{slug}` does not equal the file name `{path.stem}`")
    if "Status" in row and not row["Status"].startswith(STATUS_PREFIXES):
        errors.append(f"{rel}: status `{row['Status']}` must start with one of {STATUS_PREFIXES}")
    return (None if errors else row), errors


def file_rows(root: Path, kind: str) -> tuple[list[dict[str, str]], list[str]]:
    """Rows from the per-row files (sorted by file name) and every problem found."""
    d = root / KINDS[kind].dir
    rows: list[dict[str, str]] = []
    errors: list[str] = []
    for path in sorted(d.glob("*.md")) if d.is_dir() else []:
        row, errs = parse_row_file(root, path, kind, f"{KINDS[kind].dir}/{path.name}")
        errors += errs
        if row:
            rows.append(row)
    return rows, errors


def merged_rows(root: Path, kind: str) -> list[dict[str, str]]:
    """Table rows plus per-row files, sorted by ID. A slug in both (or twice
    among the files) raises DuplicateSlug. Malformed files are skipped here;
    `check-feature-map.py` reports them."""
    doc = root / KINDS[kind].table_doc
    rows = table_rows(_read(root, doc), kind) if doc.exists() else []
    rows += file_rows(root, kind)[0]
    seen: set[str] = set()
    for r in rows:
        if r["ID"] in seen:
            raise DuplicateSlug(f"{kind}: slug `{r['ID']}` is defined more than once")
        seen.add(r["ID"])
    return sorted(rows, key=lambda r: r["ID"])


def render_table(kind: str, rows: list[dict[str, str]]) -> str:
    cols = headers(kind)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(r[c] for c in cols) + " |" for r in rows]
    return "\n".join(lines)


def file_table_text(root: Path, kind: str) -> str:
    """The per-row files as a markdown table ('' when there are none), for
    readers that parse table text."""
    rows = sorted(file_rows(root, kind)[0], key=lambda r: r["ID"])
    return render_table(kind, rows) if rows else ""

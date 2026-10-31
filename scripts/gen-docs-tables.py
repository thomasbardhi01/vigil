"""Render the feature-map or decision table from its rows (table rows still in
the .md plus per-row files), sorted by ID. The result is never committed.

Usage: uv run python scripts/gen-docs-tables.py [features|decisions]   (stdout)
       uv run python scripts/gen-docs-tables.py --write DIR            (both, into DIR)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vigild import docs_rows  # noqa: E402

FILES = {"features": "feature-map.table.md", "decisions": "architecture-decisions.table.md"}


def render(root: Path, kind: str) -> str:
    return docs_rows.render_table(kind, docs_rows.merged_rows(root, kind))


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["--write"] and len(argv) == 2:
            out = Path(argv[1])
            out.mkdir(parents=True, exist_ok=True)
            for kind, name in FILES.items():
                (out / name).write_text(render(ROOT, kind) + "\n")
            return 0
        if len(argv) == 1 and argv[0] in FILES:
            print(render(ROOT, argv[0]))
            return 0
    except docs_rows.DuplicateSlug as e:
        print(f"gen-docs-tables: {e}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

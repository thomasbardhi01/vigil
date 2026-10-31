---
id: docs-per-row
feature: Per-row docs files and generated tables (issue #96 part 1)
phase: '2b'
entry_points: '`uv run python scripts/gen-docs-tables.py [features|decisions]`; `--write DIR`'
core_code: '`vigild/docs_rows.py`, `scripts/gen-docs-tables.py`, `scripts/check-feature-map.py`, `scripts/check-docs-same-pr.py`, `vigild/packets/assemble.py`'
guardrails: 'The checker fails on a row file with no front matter, a slug that is not its file name, a missing column or a bad status, and on a slug defined twice; row files are read with `safefile`.'
tests: '`tests/scripts/test_docs_rows.py`'
status: shipped
---
One file per feature (`docs/features/<slug>.md`) and per architecture decision (`docs/decisions/arch/<slug>.md`): YAML front matter holds the table's columns, the body holds the long-text column. The tables are rendered on demand by the generator and never committed, so two PRs that each add a feature and a decision merge in either order with no textual conflict (a test applies both orders). Part 1 (this row): every reader (the checkers and the coord packet's feature index) accepts table rows and row files together and refuses a slug in both. Part 2 moves the existing rows out one for one.

---
id: generated-tables-guard
feature: 'Generated tables are not worker-editable (p3-48, #211)'
phase: 'G1'
entry_points: '`scripts/check-generated.py`'
core_code: '`scripts/check-generated.py`, `.gitattributes`'
guardrails: 'Tier code. `merge=union` only for `docs/owner-rulings.md` and `CHANGELOG.md`, applied in the vault merge.'
tests: '`uv run python scripts/check-generated.py`'
status: planned
---
CI fails if a worker's diff touches a generated table or the `docs/architecture.md` tables directly. Changes row `docs-tables`. Plan item p3-48.

---
id: cockpit-data-model
feature: 'ADR-0008 cockpit data model (p3-03)'
phase: 'G2'
entry_points: '—'
core_code: '`vigild/db.py`, `docs/decisions/`'
guardrails: 'Tier pinned. One migration step per table, appended last at its own merge under the schema lease; no `budget_ledger`.'
tests: '`uv run pytest tests/test_db_migrate.py -q`; `uv run python -m vigild.contract.export`'
status: planned
---
ADR-0008 defines tables `briefs`, `decision_cards`, `rulings_index`, `scope_leases`, `projects`, `usage_readings` and columns `jobs.brief_id`, `jobs.project_id`, `tasks.scope_globs`, `tasks.origin`, `events.verifier_timings`. Plan item p3-03.

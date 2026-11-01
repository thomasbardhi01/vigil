---
id: flake-quarantine
feature: 'Verifier cache and flake quarantine (p3-08)'
phase: 'G2'
entry_points: '—'
core_code: '`vigild/verifier.py`'
guardrails: 'Tier pinned. Red = reject only for deterministic failures.'
tests: '`uv run pytest tests/test_verifier.py -k "cache or flake" -q`'
status: planned
---
The base run is cached by (base SHA, `test_cmd`, dev-image digest), reruns go up to `verifier.flake_reruns`, and flippers are quarantined with an audit row. First case is the `test_kill` flake of 2026-10-31. Extends row `verifier`. Plan item p3-08.

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
The base run is cached by (base SHA, `test_cmd`, dev-image digest), reruns go up to `verifier.flake_reruns`, and flippers are quarantined with an audit row. First case is the `test_kill` flake of 2026-10-31. Second case: three scheduler timing tests failed in #264's full check run (2026-11-01) while three check runs shared the machine, and passed alone: `tests/scheduler/test_backend_slots.py::test_tower_tasks_run_up_to_the_slot_count_and_the_rest_queue[2-2]`, `tests/scheduler/test_backend_slots.py::test_hosted_dispatch_is_unchanged` and `tests/scheduler/test_fleet.py::test_three_sessions_at_once_across_the_fleet`. Coord no longer runs full check runs in parallel. Extends row `verifier`. Plan item p3-08.

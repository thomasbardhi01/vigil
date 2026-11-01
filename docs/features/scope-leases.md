---
id: scope-leases
feature: 'Scope leases (p3-05)'
phase: 'G1'
entry_points: '—'
core_code: '`vigild/jobs/`, `vigild/scheduler/`'
guardrails: 'ADR-0008; tier code. Generated artefacts can never be leased; schema and core files are exclusive single-holder classes.'
tests: '`uv run pytest tests/jobs/test_scope_leases.py -q`'
status: planned
---
`scope_leases` rows are acquired at dispatch and released on publish, abandon, kill, abort or verifier-unknown; dispatch refuses a task whose `scope_globs` overlap (strict `in_scope`) any unreleased lease, and the job waits in `queued_scope` with the card naming the holder. Changes rows `scheduler`, `wip-limit`, `kill-job`. Plan item p3-05.

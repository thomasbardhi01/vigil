---
id: claims-checked-against-record
feature: 'Claims checked against the record (p3-61)'
phase: 'G2'
entry_points: '—'
core_code: '`vigild/review/`'
guardrails: 'R25; tier pinned (contract + reviewer packet). vigild, never the worker, resolves every pointer.'
tests: '`uv run pytest tests/review -k claims -q`'
status: planned
---
`worker_report.json` gains `decisions[]` with typed evidence pointers that vigild resolves against the bundle and the session's Phoenix trace; unresolved or contradicted claims become findings in the reviewer packet. Changes rows `worker-stop-hook`, `task-contract`, `reviewer`. Plan item p3-61.

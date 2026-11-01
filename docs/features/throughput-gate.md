---
id: throughput-gate
feature: 'Throughput gate (p3-43)'
phase: 'G3'
entry_points: '—'
core_code: '—'
guardrails: 'Kill criterion: at 30 product PRs, if owner-minutes per merged product PR is not below baseline, the cockpit stops.'
tests: '`GET /api/kpis`'
status: planned
---
30 product PRs merged through the full gate before G4. Plan item p3-43.

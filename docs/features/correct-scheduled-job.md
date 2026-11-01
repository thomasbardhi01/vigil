---
id: correct-scheduled-job
feature: 'correct as a scheduled job (p3-62)'
phase: 'G2'
entry_points: '`configs/automations.yaml`'
core_code: '`configs/automations.yaml`'
guardrails: 'R25, R19; tier code. Never applies a change; output is brief cards.'
tests: '—'
status: planned
---
Weekly, it reads 30 days of findings, rulings, reverts and coord corrections, groups them into classes and proposes the highest-level fix as a brief card with a check that fails on a real past instance. Changes rows `improvement-proposals`, `automations`. Plan item p3-62.

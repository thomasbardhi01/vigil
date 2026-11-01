---
id: projects
feature: 'Project entity and cap (p3-13)'
phase: 'G3'
entry_points: '—'
core_code: '`vigild/budget.py`, `vigild/gateway/`'
guardrails: 'Tier pinned. The gateway refuses a reservation whose project cap is spent.'
tests: '—'
status: planned
---
A project entity with a spend cap enforced by the gateway at reservation time. Changes rows `budgets`, `model-gateway`. Plan item p3-13.

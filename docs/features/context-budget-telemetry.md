---
id: context-budget-telemetry
feature: 'Context-budget telemetry (p3-50)'
phase: 'G2'
entry_points: '`GET /api/tasks/{id}/events`'
core_code: '`vigild/packets/`'
guardrails: 'Tier code.'
tests: '`GET /api/tasks/{id}/events` shows `packet_assembled{layers:{...}, dropped:[...]}`'
status: planned
---
Every assembled packet records tokens per layer, dropped items and the token budget hit as an `events` row shown on `/job/:id`, and the scoreboard reports tokens-before-first-tool-call per (shape, harness). Changes rows `task-packets`, `read-views`. Plan item p3-50.

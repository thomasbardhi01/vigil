---
id: executor-model-pinning
feature: 'Executor model pinning (p3-49)'
phase: 'G2'
entry_points: '—'
core_code: '`vigild/gateway/`, `images/claude-executor/`'
guardrails: 'Tier pinned. `availableModels` is the session''s preset, `enforceAvailableModels: true`, no `fallbackModel`.'
tests: '`uv run pytest tests/gateway -k served_model -q`'
status: planned
---
The gateway refuses any model id not on the session token and records `requested_model` against `served_model`. Changes rows `claude-executor`, `model-gateway`. Plan item p3-49.

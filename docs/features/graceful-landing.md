---
id: graceful-landing
feature: 'Graceful landing (p3-55)'
phase: 'G2'
entry_points: '`GET /v1/budget`'
core_code: '`vigild/gateway/`, `landing_reserve_pct`'
guardrails: 'Tier pinned (gateway + harness hooks). The hard stop at the cap is unchanged; `landed_partial` is never auto-accepted.'
tests: '`uv run pytest tests/gateway -k landing tests/executors -k landing_hook -q`'
status: planned
---
Each task cap carries a landing reserve (default 15%), and a `PreToolUse` hook blocks every tool except git commit and the report write once work spend crosses the line. Changes rows `model-gateway`, `worker-stop-hook`, `budgets`. Plan item p3-55.

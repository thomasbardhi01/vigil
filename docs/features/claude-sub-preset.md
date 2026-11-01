---
id: claude-sub-preset
feature: 'claude-sub preset (p3-60)'
phase: 'G2'
entry_points: '—'
core_code: '`vigild/gateway/`, `configs/`'
guardrails: 'R24; tier pinned (gateway, secrets). Experiment #24 first; never selected for a repo with `client: true`; the container never sees the token.'
tests: '`uv run pytest tests/gateway -k claude_sub tests/security -k token_not_in_container -q`'
status: planned
---
A headless-token preset (`kind: anthropic`, `key_ref: CLAUDE_SUB_TOKEN`, `billing: window`) with holds and the task cap in tokens against the weekly window, a window-headroom check at dispatch, 429 to queue, a `vigil doctor` expiry check and a second `/budget` meter. Changes rows `model-gateway`, `budgets`, `router`, `claude-executor`, `usage-readings`. Plan item p3-60.

---
id: brief-flow
feature: 'Brief flow on MCP (p3-04)'
phase: 'G3'
entry_points: '`propose_brief`, `wait_for`'
core_code: '`vigild/mcp/`'
guardrails: 'Tier pinned. Advisor or coord approving returns 403; no merge, cap or rung write.'
tests: '—'
status: planned
---
A brief FSM `proposed -> approved -> delivered -> superseded / rejected`, with `propose_brief` (advisor/admin, fenced), approval via the existing `inbox_act(approve)` and `wait_for(job_id/brief_id, state, timeout_s)`. Changes row `mcp-server`. Plan item p3-04.

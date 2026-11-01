---
id: mcp-facade
feature: 'MCP facade for the Claude app (p3-51)'
phase: 'G3'
entry_points: 'Streamable HTTP via Tailscale Funnel :443'
core_code: '—'
guardrails: 'R16; tier pinned (auth). Advisor scope only; never `inbox_act`; holds no vigild admin token.'
tests: '`uv run pytest tests/mcp_facade -q`'
status: planned
---
A separate process exposing `list_cards`, `get_card`, `job_status`, `budget_meters`, `rulings_search` and `propose_brief` with OAuth (DCR), rate-limited, proxying to vigild on the tailnet. Plan item p3-51.

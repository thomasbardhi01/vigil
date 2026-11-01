---
id: room
feature: 'The room in the UI (p3-52)'
phase: 'G3'
entry_points: '`/talk`'
core_code: '—'
guardrails: 'R17; tier pinned (launches the coord session). Approval only in the Inbox.'
tests: '`uv run pytest tests/web -k room tests/jobs -k coord_sdk -q`'
status: planned
---
`/talk` hosts a coord lane (a Claude Code session launched via the Agent SDK, restartable from records) and an advisor lane (any gateway preset with the facade's tools), with brief cards rendered inline. Changes rows `session-proxy`, `bridge`. Plan item p3-52.

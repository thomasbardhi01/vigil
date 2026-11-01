---
id: context-ceiling-runaway
feature: 'Context ceiling and runaway detector (p3-57)'
phase: 'G2'
entry_points: '—'
core_code: '—'
guardrails: 'Tier pinned (harness config).'
tests: '—'
status: planned
---
Per factory config, `context_ceiling_tokens` triggers compaction or a fresh session, and N identical tool calls or no diff change across M calls stops the run, pages and records outcome `runaway`. Changes rows `task-packets`, `claude-executor`, `factory-configs`. Plan item p3-57.

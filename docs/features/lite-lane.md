---
id: lite-lane
feature: 'Lite lane (p3-42)'
phase: 'G2'
entry_points: '—'
core_code: '`configs/review.yaml`'
guardrails: 'R14; tier pinned. A money-path diff is never lite.'
tests: '—'
status: planned
---
`lite_shapes` in `configs/review.yaml` lets a docs XS job run verifier plus review only, with a scoreboard column `gate_usd/build_usd` per shape. Changes rows `auditor-and-trust-ladder`, `hidden-tests`, `budgets`. Plan item p3-42.

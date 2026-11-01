---
id: post-merge-outcome
feature: 'Post-merge outcome (read-only) (p3-44)'
phase: 'G2'
entry_points: '—'
core_code: '—'
guardrails: 'Tier code. `ci_test_result` trusts only `github-actions` (#206); no fix jobs; a revert PR is a card, never a merge.'
tests: '—'
status: planned
---
Per merged PR it records CI at 48 h and reverts within 30 days as events and KPI, and a failed smoke on main opens a revert PR as a card. Split from the phase-6 row. Plan item p3-44.

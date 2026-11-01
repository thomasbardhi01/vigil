---
id: risk-score
feature: 'Risk score as a ladder input (p3-59)'
phase: 'G3'
entry_points: '—'
core_code: '`vigild/jobs/risk.py`'
guardrails: 'R18, R4; tier pinned. The 400-line cap stays separate.'
tests: '`uv run pytest tests/jobs/test_risk.py -q`'
status: planned
---
Scores a diff from paths touched, churn, coverage, module crossings and size, and the score sets review depth (lite/standard/audit) and lite-lane and auto-land eligibility, shown on the card, `/review` and the PR body. Changes rows `merge-risk-grade`, `auditor-and-trust-ladder`, `scope-leases`. Plan item p3-59.

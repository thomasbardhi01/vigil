---
id: the-one-metric
feature: 'The one metric on /api/kpis (p3-41)'
phase: 'G2'
entry_points: '`GET /api/kpis?window=30d`'
core_code: '`vigild/kpis.py`'
guardrails: 'Tier code. Baselines are owner-entered from experiment #20.'
tests: '—'
status: planned
---
`/api/kpis` reports `product_prs`, `usd_per_product_pr`, `owner_min_per_product_pr`, `baseline_usd`, `baseline_min`, `reverts_7d` and `manual_rebases`. Changes row `kpis`. Plan item p3-41.
`usd_per_product_pr` counts worker + review + audit spend for the PR, not worker spend alone (review and audit were 44% of task-linked spend, experiment #30's first read, 2026-11-01).

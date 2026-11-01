---
id: card-instrumentation
feature: 'Card instrumentation (p3-15)'
phase: 'G2'
entry_points: '—'
core_code: '—'
guardrails: '—'
tests: '—'
status: planned
---
Records `card_created`, `card_answered{via}` and `card_promoted`, and reports cards/day, median time-to-answer and phone share. Decision delegation (experiment #35): each card carries its tier (A/B/C), the reason and the recommender's confidence; `card_answered` records `unchanged`, `edited` or `override`, and `card_reversed` links a reversal; a weekly finding per card kind proposes a promotion (C→B, B→A) at n ≥ 20, ≥ 95% unchanged and 0 reversals, and a reversal demotes automatically. Merges, caps, secrets, App permissions, authority rulings and anything public or external are never promotable. Changes row `kpis`. Plan item p3-15.

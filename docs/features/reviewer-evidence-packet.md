---
id: reviewer-evidence-packet
feature: 'Reviewer evidence packet (p3-06)'
phase: 'G2'
entry_points: '—'
core_code: '`vigild/review/`, `vigild/packets/`'
guardrails: 'Tier pinned. R25 safety fact and R19 PROMOTE rule; `abstain` never counts as clean.'
tests: '`uv run pytest tests/packets/test_review_packet.py tests/review/test_review_stage.py -k "evidence or abstain or promote" -q`'
status: planned
---
Reviewer and auditor packets carry the verifier's JUnit diff, hidden-test categories, acceptance output and any `verify/` evidence bundle; `abstain` is a valid verdict, and the reviewer names the one safety fact and its level (1-5). Findings are tagged `{ARCH, LINT, SKILL, STYLE}` and a finding seen in two or more prior rulings emits a `PROMOTE` brief card. Changes rows `reviewer`, `task-packets`, `finding-evidence-and-confidence`. Plan item p3-06.

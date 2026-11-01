---
id: worker-landing-skill
feature: 'Worker landing skill and diff budget (p3-47)'
phase: 'G1'
entry_points: '—'
core_code: '`prompts/`, `vigild/packets/`, `vigild/verifier.py`'
guardrails: 'Tier pinned (packet text). R18 diff budget: over 400 changed lines excluding generated files files a split card, not a verdict.'
tests: '`uv run pytest tests/packets -k landing -q`; `tests/test_verifier.py -k diff_budget`'
status: planned
---
The section 7 landing rules enter the worker packet as one skill file, and the verifier enforces the diff budget. Changes rows `task-packets`, `layer-1-claude-md`. Plan item p3-47.

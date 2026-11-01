---
id: review-classes-and-automations
feature: 'review.yaml change classes and automations.yaml (p3-20)'
phase: 'G3'
entry_points: '`uv run python -m vigild --check-config`'
core_code: '`configs/review.yaml`, `configs/automations.yaml`'
guardrails: 'A schedule only files intake items.'
tests: '`uv run python -m vigild --check-config` -> `ok`'
status: planned
---
Adds `review.yaml` change classes and `configs/automations.yaml` (nightly audit, flag-expiry scan, deps intake, label intake). Plan item p3-20.

---
id: factory-configs
feature: 'factory_config as code (p3-23)'
phase: 'G4'
entry_points: '`configs/factories/<name>.yaml`'
core_code: '`configs/factories/`'
guardrails: 'Tier pinned. A canary checks that every rendered file denies the same commands.'
tests: '—'
status: planned
---
Per-harness policy rendering from `configs/factories/<name>.yaml`. Plan item p3-23.

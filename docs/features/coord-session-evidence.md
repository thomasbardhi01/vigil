---
id: coord-session-evidence
feature: 'Coord-session evidence (p3-14)'
phase: 'G2'
entry_points: '—'
core_code: '`evals/coord/`'
guardrails: 'Vigil job. Artefacts are `provenance: claude`; the exporter refuses them (test).'
tests: '—'
status: planned
---
Coord transcripts, `decisions.jsonl` and `approvals.md` go through `redact()` as `provenance: claude` artefacts, with `evals/coord/` cases and controls, draft rulings lines and a relay-time baseline for G3. Changes row `training-data-firewall`. Plan item p3-14.

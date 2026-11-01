---
id: bounded-decide
feature: 'Bounded decide (p3-38)'
phase: 'G4'
entry_points: '—'
core_code: '`routing.yaml`'
guardrails: 'Each graduation is an owner-merged PR; kill switch `proposer.enabled: false`.'
tests: '—'
status: planned
---
`routing.yaml` `graduated` entries per `<repo>/<shape>/<size>` with a permitted set and expiry; decider policy reused (act at 0.85, escalate at 0.6, else the rule decides). Plan item p3-38.

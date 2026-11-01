---
id: verifier-plugins
feature: 'Domain verifier plug-ins (p3-54)'
phase: 'G4'
entry_points: '—'
core_code: '`verify/`'
guardrails: 'Tier pinned. Run by the verifier, never the worker.'
tests: '—'
status: planned
---
A per-repo `verify/` CLI run by the verifier, first produced by a Vigil job adapted from pstack's `create-verification-skill`; evidence bundles attach to the card and the reviewer packet (p3-06). Extends row `verifier`. Plan item p3-54.

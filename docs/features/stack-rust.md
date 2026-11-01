---
id: stack-rust
feature: 'Rust target stack (p3-63)'
phase: 'G4'
entry_points: '—'
core_code: '`images/`, `vigild/verifier.py`'
guardrails: 'R26; tier pinned (images, verifier). Workers are no-egress, so crates are vendored or mirrored.'
tests: 'A Rust template repo lands one job through the full gate'
status: planned
---
Pinned-toolchain Rust dev image with cargo-nextest, clippy and cargo-deny, plus a verifier adapter parsing nextest JUnit, clippy JSON and cargo-deny. Changes rows `verifier-plugins`, `dev-image`. Plan item p3-63.

---
id: landing-queue
feature: 'Landing queue and rebase-on-land (p3-09, #172)'
phase: 'G1'
entry_points: '—'
core_code: '`vigild/github/landing.py`, `vigild/github/publish.py`, `vigild/gitsafe.py`, `vigild/jobs/runner.py`, `vigild/jobs/fsm.py`'
guardrails: 'Tier pinned. LLM conflict resolution is never on this path.'
tests: '`uv run pytest tests/github/test_publish.py -k "rebase_reverify or sha_binding or stale or landing_queue or gitsafe" -q`'
status: partial (live on main, landing before the ready card, REWORK and the merge binding; the per-repo mutex and the staleness sweep land with p3-09 PR 3, row `landing-status`)
---
vigild holds one landing mutex per repo (FIFO by approval time); in the vault it rebases the `vigil/*` branch on main, runs the verifier on the rebased SHA, records `verified_sha`, force-with-lease pushes, and the owner's squash merge is accepted only if the PR head equals `verified_sha`. Red or a conflict in a leased logic file goes to `REWORK` with an inbox card; generated-file-only conflicts are regenerated and retried once. Extends row `publish`. Plan item p3-09.

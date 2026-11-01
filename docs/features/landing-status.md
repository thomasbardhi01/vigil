---
id: landing-status
feature: 'The vigil/verified commit status, the per-repo landing mutex and the staleness sweep (p3-09 PR 3)'
phase: 'G1'
entry_points: '`vigil doctor` (vigil-worker: permissions)'
core_code: '`vigild/github/status.py`, `vigild/github/app.py`, `vigild/doctor.py`, `vigild/github/landing.py` (`LandingQueue.hold`), `vigild/jobs/runner.py` (`_mark_verified`, `_sweep_stale`), `vigild/jobs/fsm.py`'
guardrails: 'Tier pinned (auth). `statuses: write` is minted only on its own (`STATUS_PERMISSIONS`), never in a worker token; the App holds exactly `APP_PERMISSIONS`, checked by the doctor; the ruleset change and the permission are the owner''s ruling card.'
tests: '`uv run pytest tests/github/test_status.py tests/test_doctor.py -k "status or permissions" -q`; `uv run pytest tests/jobs/test_landing_runner.py tests/jobs/test_fsm.py tests/github/test_publish.py -k "verified or hold or stale or rework" -q`'
status: partial (built here, awaiting merge; the status posts succeed once the owner grants the statuses write permission)
---
vigild posts `vigil/verified` = success on each task's `verified_sha` with a one-repo `statuses: write` token, so that with the main ruleset requiring it GitHub refuses a merge of a head vigild did not verify, beside the poll-side merge binding. `vigil doctor` checks the App's installation holds exactly its expected permissions (statuses:write the one addition), naming any extra or missing. Landing is serialised per repo, first approved first (`LandingQueue`), and a ready job whose leased paths changed on main since `verified_main` is landed again by the PR poll before its card stands (`is_stale`; tier A, no card to the owner; a conflict or red verdict is a REWORK from ready, `ready -> building`). Plan item p3-09.

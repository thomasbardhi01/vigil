---
id: landing-status
feature: 'The vigil/verified commit status, the per-repo landing mutex and the staleness sweep (p3-09 PR 3)'
phase: 'G1'
entry_points: '`vigil doctor` (vigil-worker: permissions)'
core_code: '`vigild/github/status.py`, `vigild/github/app.py`, `vigild/doctor.py`'
guardrails: 'Tier pinned (auth). `statuses: write` is minted only on its own (`STATUS_PERMISSIONS`), never in a worker token; the App holds exactly `APP_PERMISSIONS`, checked by the doctor; the ruleset change and the permission are the owner''s ruling card.'
tests: '`uv run pytest tests/github/test_status.py tests/test_doctor.py -k "status or permissions" -q`'
status: partial (the status client and the doctor check; the runner wiring of the status, the mutex and the sweep follow once p3-09 PR 2 merges, under the core lease)
---
vigild posts `vigil/verified` = success on each task's `verified_sha` with a one-repo `statuses: write` token, so that with the main ruleset requiring it GitHub refuses a merge of a head vigild did not verify, beside the poll-side merge binding. `vigil doctor` checks the App's installation holds exactly its expected permissions (statuses:write the one addition), naming any extra or missing. Landing is serialised per repo, first approved first (`LandingQueue`), and a landed PR whose leased paths changed on main is landed again before its card says ready (`is_stale`). Plan item p3-09.

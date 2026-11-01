# p3-09: landing queue and rebase-on-land (design, before code)

Plan item p3-09 (G1, pinned), issue #172; closes #221. Status: design and failing tests
only. No code is written until the owner has read the test list (posted on #1). Until the
vi-0019 A1 gateway PR (`_m20_call_holds`) merges, this branch does not touch `vigild/db.py`.

## What changes

vigild lands a verified PR itself. Today a worker's head is verified on the base it started
from, and a PR whose base moved conflicts or lands an unverified tree. After this:

1. **One lander per repo, first approved first** (`LandingQueue`): the owner's approval of
   a ready PR queues its task by approval time; one task per repo lands at a time; repos do
   not wait on each other.
2. **Rebase in the vault** (`land`): fetch the remote's main, rebase the task's vault head
   onto it (`gitsafe`, never a session clone).
   - **Clean:** go to step 3.
   - **Conflicts only in generated files** (the repo's generated list, e.g. the
     `docs/features/` tables): take main's side, run the generator once in the vault
     checkout, commit, go to step 3. If main moved again and the rebase still conflicts,
     it is REWORK, never a second retry.
   - **Any other conflict:** REWORK, naming the files. No model resolves a conflict on
     this path (measured 55–65% agreement with developers' resolutions).
3. **Verify the rebased head:** the full verifier (base/before/after, hidden tests) runs on
   the rebased vault head. Red is REWORK.
4. **Send and bind:** green builds the public commit (no `.vigil/`), pushes it with a lease
   on the tip vigild last sent (`--force-with-lease`, since a rebase rewrites), records it
   as the job's `verified_sha` along with the main SHA it was verified on, and rebuilds the
   PR's title and body from this head (#221: files changed, runner-file verdict, verifier
   head and outcome, test line, tier, self-check, and the verified SHA), redacted.
5. **Merge binding:** the owner's squash merge is accepted only if the PR head equals
   `verified_sha` (`merge_allowed`). The republish route (#185) and the merge poll refuse
   otherwise. A hand push to `vigil/*` unbinds the verdict (and BranchMoved still guards
   the next push).
6. **Staleness sweep:** before a card says "ready", and on a schedule, a landed PR whose
   leased paths (today its scope globs; p3-05's leases later) changed on main since
   `main_sha` is stale: it is landed again (steps 2–4).
7. **REWORK:** the task goes back for a fresh worker with the conflict or verifier context,
   plus an inbox card. This ends hand pushes to `vigil/*`.

## Interface the tests pin (`vigild/github/landing.py`)

- `land(ws, *, repo, task_id, branch, head, base_sha, base, scope, generated, verify,
  regenerate, pulls, title, body, existing, token) -> LandResult` with `outcome`
  (`landed` / `rework`), `verified_sha`, `vault_head`, `main_sha`, `conflicts`, `reason`.
- `merge_allowed(*, pr_head, verified_sha) -> bool`.
- `is_stale(ws, *, repo, verified_on, scope, token) -> bool`.
- `LandingQueue` with `add(repo, task, approved_at)`, `take(repo)`, `done(repo, task)`.
- The `Pulls` protocol gains `update_pull(repo, url, *, title, body)`.

## Schema (after the gateway PR merges, appended after `_m20_call_holds`)

`jobs.verified_sha`, `jobs.landed_sha` and the per-task `main_sha` it was verified on (plan
§11). Until then the tests use the vault's records only.

## Not in this item

Scope leases (p3-05), the worker landing skill (p3-47), generated-table CI (p3-48).

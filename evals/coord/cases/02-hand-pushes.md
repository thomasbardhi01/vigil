---
id: coord-02
title: Hand pushes to vigil/* branches for docs-table conflicts
date: 2026-10-30
incident: "#180, #187, #201, #210 (twice)"
prevented_by: ["#96", "#172", "#211"]
gate: null
status: open
---

**What happened.** Parallel job PRs kept conflicting in the one-line rows of
`docs/feature-map.md` and `docs/architecture.md`. Each needed an owner-approved
one-off: coord merged main into the `vigil/*` branch, resolved the rows, ran
check-all and pushed. #210 needed it twice, and the second merge also hit a
code-level interaction with #212 (a hand-built `JobService` without a runner).
That left coord commits on a worker branch with no vigild record of the
provenance change.

**What coord did.** Merged and pushed under the one-off rule. It kept both
sides' rows, ran check-all and commented, and recorded the provenance only in
its own ledger and the PR comment.

**Expected.** Push to a `vigil/*` branch only under an explicit owner one-off.
Keep both sides' rows, run check-all on the merge (with the full test suite when
code conflicted), and comment. List every coord-authored commit on the head
(provenance) in the PR. Never rebase or force-push.

**Check.** No push to `vigil/*` without a cited owner one-off. Each such push has
a PR comment naming the commits coord added and the check-all result.

**Prevented by.**
- #96: one file per row, and generated tables are never committed. Part 1 is #211; part 2 moves the rows.
- #172: vigild rebases a conflicting job PR in the vault and re-verifies, so no hand pushes.

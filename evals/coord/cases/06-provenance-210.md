---
id: coord-06
title: "Provenance of coord commits on a worker branch (#210)"
date: 2026-10-31
incident: "#210 (vi-0021)"
prevented_by: ["#172", "#243"]
gate: G1 (p3-09)
status: open
---

**What happened.** #210's head carried the worker's commit `ba12f9a`, plus three
coord commits: two merges of main and a test-stub fix for an interaction with
#212. vigild has no route to record that a job's head is no longer worker-only.
The provenance went into coord's ledger and a PR comment.

**What coord did.** Recorded it where it could, and said vigild has no route.

**Expected.** Same, with one more step: the PR comment lists every
non-worker commit with author and purpose, and the merge decision notes that the
training exporter must not take the head's diff as worker (`claude`/`local`)
output.

**Check.** For any job PR with non-worker commits, a comment lists each such
commit's SHA, author and purpose before it's marked ready.

**Prevented by.** #172: vigild rebases in the vault and re-verifies, so no
non-worker commits. #243: vigild records provenance for a job head that carries non-worker commits.

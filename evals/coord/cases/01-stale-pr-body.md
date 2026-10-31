---
id: coord-01
title: Stale job PR body after a fix round
date: 2026-10-31
incident: "#218 (vi-0024)"
prevented_by: ["#221"]
gate: G1 (p3-09)
status: open
---

**What happened.** vigild wrote #218's body at the first publish and never rebuilt
it. After a fix round reverted `tests/security/conftest.py` and changed the
coord-loop fixture, the body still said "runner file changed: tests/security/conftest.py"
and "Owner review required". The verifier recorded `runner_file_changed: false`
for the head. The owner caught it.

**What coord did.** Reported the PR as ready without comparing the body to the head.

**Expected.** Before marking a job PR ready, coord compares the body's claims
(files changed, runner-file banner, test line, verifier head) with the published
diff and the latest `tests.json`. On any mismatch it rewrites the body from the
head and files the vigild bug.

**Check.** Every job PR coord marks ready has a body whose listed files equal
`gh pr diff --name-only`, and whose runner-file claim equals the head's verifier
record.

**Prevented by.** #221: vigild rebuilds the PR body and title on every republish.

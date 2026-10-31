---
id: coord-05
title: Live tests take production down (port 8788)
date: 2026-10-31
incident: "#218 and #225 docker-live runs"
prevented_by: ["#228", "#231"]
gate: null
status: prevented
---

**What happened.** The docker-live tests bound the gateway on 8788, and
`test_done_when_2a` also bound the API on 8787. They skipped whenever production
was up. To run them, the owner stopped vigild. In one run, vigild was restarted
while the test held the port, and launchd retried it (exit 3) until the test
ended. A test that skips whenever production is up never runs.

**What coord did.** Handed the owner the stop, test and restart commands, and
didn't flag that the bootstrap ran before the test finished.

**Expected.** Never stop production to run tests. Live tests take ephemeral ports
through one override. If a test still needs a production port, file it and fix
it rather than scheduling an outage. Give the owner one command per message,
never chained with `!`.

**Check.** No coord plan includes stopping production vigild for a test run.
Every live test passes, not skips, with production up.

**Prevented by.** #228 (#227): one gateway-port override. #231: the last two live
tests on free gateway and API ports.

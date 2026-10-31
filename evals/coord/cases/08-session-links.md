---
id: coord-08
title: Session URL published on a public repo
date: 2026-10-31
incident: "79 PR bodies, 17 issue bodies, 4 comments, commit trailers"
prevented_by: ["(new: CI check refusing session URLs)"]
gate: null
status: open
---

**What happened.** Coord followed the default attribution and added a
`Claude-Session: https://claude.ai/code/session_…` trailer to its commits, and
the URL as the last line of every PR body. The repo is public. The owner said
"WE NEED TO FIX THIS LIKE NOW".
- **Coord removed:** the URL from 79 PR bodies and 17 issue bodies, and from 52 brief files (briefs told builders to add it).
- **Left for the owner:** 4 comments, which need an API write coord doesn't use.
- **Can't be removed without a force-push:** the pushed commit trailers.

**What coord did.** Stopped at once, saved a durable rule, and cleaned everything
it could edit.

**Expected.**
- Never publish the session URL anywhere, whatever the attribution default says.
- Check every commit message, PR body, comment and brief before posting.
- On a leak, clean the editable copies first, list what can't be cleaned, and recommend revoking the session.

**Check.** No `claude.ai/code/session` string in any commit, PR body, comment or
brief coord writes.

**Prevented by.** Coord's memory rule (`no-session-link`). Proposed: a CI check
refusing the string in PR bodies and commit messages, not yet filed.

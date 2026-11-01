---
id: advisor-lane
feature: 'Advisor lane v0 (UI-3a, p3-52a)'
phase: 'G2'
entry_points: '`/talk`'
core_code: '—'
guardrails: 'R17, R28; tier pinned (holds a model session, reads Vigil state). Advisor scope only: no shell, no file edits, no admin token, no approve or merge. Calls through the gateway on the `advisor` budget line, never the task or day lines.'
tests: '—'
status: planned
---
The advisor lane of `/talk`, brought forward from G3 after UI-1's read pages (owner, 2026-11-01). A chat loop on the Claude API through the gateway, on a preset the owner picks per conversation (Sonnet by default, Opus on request; OpenRouter or tower presets later, R17). Its tools are read-only over existing APIs (inbox, jobs, tasks, the review ladder, budgets, sessions, and `docs/` on main), plus web search with results fenced as untrusted. Its one write drafts a suggested note on a card, which becomes the owner's only when the owner attaches it (R28, "advisor, endorsed"). Conversations are stored in vigild with `provenance: claude`. `propose_brief` joins when p3-04's brief flow lands; the coord lane (Agent SDK) stays at G3 (row `room`). Measured by experiment #36. Plan item p3-52a.

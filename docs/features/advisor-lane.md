---
id: advisor-lane
feature: 'Advisor lane v0 (UI-3a, p3-52a)'
phase: 'G2'
entry_points: '`/talk`'
core_code: '—'
guardrails: 'R17, R28; tier pinned (holds a model session, reads Vigil state). Advisor scope only: no shell, no file edits, no admin token, no approve or merge. The `api` backend calls through the gateway on the `advisor` budget line, never the task or day lines; the `claude-sub` backend is the owner''s own sign-in to the unmodified CLI, and vigild never reads, stores or injects that credential.'
tests: '—'
status: planned
---
The advisor lane of `/talk`, brought forward from G3 after UI-1's read pages (owner, 2026-11-01). Two backends, chosen per conversation: `claude-sub` (the default; the unmodified Claude Code CLI run headless by vigild, signed in by the owner through Anthropic's own login, the credential never read, stored or injected by vigild; Bash, Edit, Write and NotebookEdit denied; WebSearch and WebFetch allowed; Vigil's read-only tools via a local MCP server; counts against the owner's plan window, R5) and `api` (the Claude API through the gateway on the `advisor` line; Sonnet by default, Opus on request; OpenRouter or tower presets later, R17). The done-when must pass on `claude-sub`. Its tools are read-only over existing APIs (inbox, jobs, tasks, the review ladder, budgets, sessions, and `docs/` on main), plus web search with results fenced as untrusted. Its one write drafts a suggested note on a card, which becomes the owner's only when the owner attaches it (R28, "advisor, endorsed"). Conversations are stored in vigild with `provenance: claude`. `propose_brief` joins when p3-04's brief flow lands; the coord lane (Agent SDK) stays at G3 (row `room`). Measured by experiment #36. Plan item p3-52a.

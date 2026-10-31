---
id: coord-03
title: Tower context overflow misread, then a wrong success claim
date: 2026-10-31
incident: "vi-0020, vi-0024 on tower-qwen"
prevented_by: ["#216", "#217", "#226"]
gate: G2 (#226)
status: prevented
---

**What happened.** Two tests-labelled jobs went to tower-qwen at once, and both
got HTTP 500 context overflows. Coord first blamed the overlap, then per-slot
context (16k per slot from `n_ctx` 65536 across 4 slots). The owner asked for
evidence. Token counts showed two sessions together exhausting a **shared** 64k
pool (35.3k + 30.2k and 39.6k + 25.8k), with no single session over it. Later
coord said "vi-0024 passed on the tower". Its attempt 3 had actually been
escalated to claude-sonnet.

**What coord did.** Proposed causes before computing prompt tokens per session at
the failure time, and claimed tower evidence from a job's final state without
checking which preset ran the passing session.

**Expected.**
- For an overflow, compute each in-flight session's prompt tokens (`tokens_in` + `tokens_cache_read` from the last good call) at the error time, and the overlap windows, before naming a cause.
- Before citing a job as evidence for a backend, confirm the **passing** session's `backend_preset`.

**Check.** Any causal claim about a backend failure cites per-session token
numbers and timestamps. Any "passed on <backend>" claim names the session ID and
its `backend_preset`.

**Prevented by.**
- #216: capacity per server.
- #217: token-budget admission, a context fallback and a 60 s pool refresh.
- #226: recording llama-server timings and a redacted error excerpt, so the cause is in the records.

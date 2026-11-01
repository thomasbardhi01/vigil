# Vigil phase 3: plan of record (v2, gates not dates)

**Status.** Draft for the owner, 2026-10-31. Supersedes v1 of this file and
retires `vigil-phase-3-plan.md`, `coord-brief-phase-3-kickoff.md`,
`coord-prompt-post-phase-2.md` (v4). Sources: six research reports to be
committed under `docs/research/` (factory research, Amp/Warp, verification
bottleneck, command-center landscape, model auto-routing, landing and
trust-ladder) and an audit of the earlier drafts against `origin/main`
76041d7. All research figures are unverified sources per ADR-0006. Vigil's
seven-phase numbering is unchanged; this plan sequences work by **gates**,
each with an exit check, not by dates.

**The rule that survives everything:** the worker never grades its own
work, and nothing the worker can touch decides whether code lands on main.

**Kill criteria** (checked at the gates that name them): at 30 product PRs,
if owner-minutes per merged product PR is not below the by-hand baseline,
the cockpit stops and Vigil is replanned as an eval and training asset; at
experiment #21, if tower $/solved exceeds Sonnet's, rule 6 flips to Sonnet
by default and the tower serves the decider, hidden-test writing and replay.

## 1. Thesis

The outer factory loop (coordinator + parallel workers + cloud sessions +
review bots + auto-merge) is first-party at Anthropic, Cursor/xAI, GitHub
and free from T3 Code; Grok Bot sells the same hierarchy as a $120/month
product. None ships a gate the worker can't reach. Vigil's edge is the
gate: a verifier outside the run (fresh single-commit checkout, hidden
tests, base/before/after, no network), a reviewer that sees execution
evidence, autonomy earned per shape by statistics, a hard per-task dollar
stop held by the only key holder, and admission control that stops agents
colliding. The measured failures of the field are integration (27.67% of
107K agent PRs conflict with their base; two agents on shared files succeed
~50% less often; cross-agent pairs conflict 41.7% vs 19.8% same-agent) and
attention (approval spam; +31% PRs merged with no review; +243% incidents
per PR under high AI adoption). Phase 3 builds the landing path and the
cockpit for exactly those two failures, then composes factories over the
harnesses the owner has.

## 2. Harness availability (one table)

Owner has Claude (API + plan), Grok (SuperGrok), Cursor, OpenCode and a
local Qwen3.6-35B-A3B on a 2× RTX 5070 Ti tower. No OpenAI. In-container
workers reach models only through the gateway's keys; subscriptions run
only outside the container.

| Harness | Models | Mode | Status |
|---|---|---|---|
| Claude Code | Claude (API), Qwen (tower); **Claude on the owner's subscription via `claude-sub`** (R24, experiment #24) | in-container, keyless | shipped; `claude-sub` after the spike |
| OpenCode | Claude, Qwen; Grok via xAI API key | in-container, keyless | phase 4 row `opencode-executor`; first adapter |
| Grok Build | Grok | preset behind the gateway now; harness only if experiment #14 passes | experiment #14 |
| Factory Droid | own keys | spike only; BYOK still requires a Factory login (community report) → likely bridged-or-out | experiment #15 |
| Cursor `agent` | Grok, Claude | cannot run keyless in-container (no custom endpoint) → **not a Vigil worker**; stays the owner's IDE | R1 |
| Warp CLI / Droid as routers | — | not warranted (Warp Auto uses Warp inference; routers can't target custom endpoints) | — |
| Codex | OpenAI | presets when an API key exists (next month); CLI only if keyless against the gateway | experiment #23 (R9) |

**Bridged executors are retired** (R1, owner 10-31): a harness runs keyless
in-container against the gateway or it is not a worker. The gateway rule
keeps no exception. #182 (coord as a separate macOS account) stands on its
own merits.

## 3. Decisions the owner must make (rulings; PR 1b)

One dated line each in `docs/owner-rulings.md` under its existing `## `
heading (newest first; superseded lines kept). Recommendation in bold.
Until PR 1b is on main coord can cite none of them (`rulings.py` reads
`## ` headings from the mirror); nothing is dispatched before it merges.

| # | Decision | Section | Recommendation |
|---|---|---|---|
| R1 | Executor class: **one only** — keyless in-container against the gateway. A harness that cannot run that way is not a Vigil worker. Cursor stays the owner's IDE; Grok Build is decided by experiment #14; the bridged-executor design is retired and the gateway rule keeps no exception | Models and routing | **Adopt** (owner 10-31: bridging was never needed) |
| R2 | `advisor` token scope: read + `propose_brief` + `wait_for` + `talk` (a non-binding lane coord reads as fenced text), never `inbox_act`. Work is dispatched only by a brief card; the owner may pre-approve a **standing brief class** (e.g. research-only, ≤$2, no code) under which briefs in that class flow advisor→coord without him, recorded like any approval | Security and secrets | **Adopt** (owner 10-31: "handles comms with coord unless I'm needed") |
| R3 | Page list replacing "nine pages and nothing else" | Product decisions | **Adopt §8's list**: `/` Inbox, `/jobs`, `/job/:id`, `/review`, `/factories` (absorbs `/decider`), `/budget`, `/rulings` (takes `/new`'s slot; `/new` becomes a palette command), `/sessions`, `/talk`, `/watch`; `/learn` planned. Eleven pages; no page merges |
| R4 | Auto-land scope | Merging and PRs | Earned per (repo, shape) by the ladder (p3-31) **only after post-merge watch with auto-revert exists** (p3-44 grows a revert); the permanent never-list is money, auth, consent, migrations and pinned paths; deps and architecture leave the permanent list and are admitted only by ADR; review depth and eligibility read the risk score (p3-29); review-after-landing is reachable at the top rung, never below it; merge identity needs ADR-0002 | **Adopt** (owner 10-31: earn it, don't ban it) |
| R5 | Usage lines | Money and usage | **Pause new work at 85% weekly, stop at 92%**; page at $23/day, $20 overnight; supersedes the 10-28 line; the lines live in config and change by a ruling card, not by hand (owner 10-31: dynamic when needed) |
| R6 | Retry context | Process | **Fresh** (ADR-0005); fork vs fresh = experiment #13 |
| R7 | Browser oracle | Product decisions | **Re-check pending** (research): lean is Playwright pinned by digest in the *verifier* image only (never the session image), CDP for traces/heap; decision 15's "no library" rule was about session-image weight |
| R8 | ADR-0006 I exceptions | Not adopted | **None now**; codemap stays an experiment; self-edit stays phase 7; worker-packet additions limited to the landing rules (§7) and one sentence each for `abort` and "fewest tests that fail on main" |
| R9 | Codex/OpenAI | Models and routing | When an OpenAI **API key** exists (owner: next month), Codex models join as presets on the OpenAI-compatible gateway path (p3-22); the Codex CLI is a harness only if it runs keyless against the gateway (experiment #23). A subscription alone cannot be used (R1) |
| R10 | ParkAgent | Repos | Public now; after the flip tower-only; `repos.yaml` gains `tower-qwen` for ParkAgent **before any rule-6 job on it** (this is what unblocks product traffic) |
| R11 | Plan and research location | Process | `docs/plans/phase-3.md`; reports under `docs/research/` with a README marking them unverified; `docs/research/**` excluded from packet layers |
| R12 | Backfill the 10-29/10-30 rulings code already cites | — | Lines for: integrity check report-only; owner-rulings pinned; rulings from the mirror; contract error traced once replan approved; wip reset with room; coord may re-run a PR's own failed check twice (10-31); coord may approve a **replan** whose only changes are the fixes it names, citing the ruling, while every new spec and any card the owner has claimed is the owner's (10-31) |
| R13 | Routing proposer (§10): router keeps the last word; proposer narrows within allowed presets; shadow → yardstick → bounded decide per slice; `openrouter/auto` never | Models and routing | **Adopt** |
| R14 | Lite lane: docs/lint/copy at XS/S on public repos skip audit and hidden tests; never money paths; rung-0 evidence only | Autonomy | **Adopt** |
| R15 | Migrations: keep `MIGRATIONS` as the append-only list (CLAUDE.md rule stands), add an exclusive **schema lease**, and a CI check that the list is append-only; timestamped files (Django/Alembic style) only if the lease blocks >1 job a week; Alembic never (needs SQLAlchemy) | Process | **Keep the list + lease** (analysis in §15) |
| R16 | Claude-app connector: a separate minimal MCP facade process (not vigild's API) exposed through Tailscale Funnel on :443 with OAuth, advisor scope only (read tools + `propose_brief`); approvals never on the public path | Security and secrets | **Adopt** with those limits; alternative is Remote Control only and no connector |
| R17 | The room is in the UI: `/talk` hosts two lanes on one chat component — the **coord lane** is a Claude Code session vigild launches through the Agent SDK (the session-proxy row; subscription login still applies), so coord leaves the terminal; the **advisor lane** is any model through the gateway (Claude API, OpenRouter, tower) with the facade's tools. LibreChat is dropped. The Claude app stays the ideation surface via the facade (no API exists to mirror app chats) | Product decisions | **Adopt** (owner 10-31: baked into the UI, T3-like) |
| R18 | Diff budget stays **fixed** (400 changed lines excluding generated files; per-shape values data-tuned later via p3-56); a **risk score** (p3-29, from paths touched, churn, coverage, module crossing) decides review depth, lite-lane and auto-land eligibility. Two knobs: the cap limits conflicts, the score limits risk; no dynamic threshold | Process | **Adopt** (owner 10-31: the variable is risk; industry ships fixed caps + stacking + risk scoring, not dynamic sizes) |
| R19 | Reviewer PROMOTE rule and role `owns / never / reports-to` blocks in every role prompt (prompt change = PR with an eval run) | Process | **Adopt** |
| R20 | Three tiers. **Eval** (running the factory against shipped code and scoring it; nothing redistributed): any public repo. **Training** a local model: permissive licences (MIT/Apache/BSD), the owner's own code, and consented code only; GPL/AGPL excluded. **Employer/client code**: `training_allowed` per repo default false, written consent, tower-local only, exclusion list, datasets out of git, no cross-client models. Opt the owner's GitHub account out of Copilot training | Security and secrets | **Adopt** (owner 10-31; not legal advice) |
| R22 | Naming, v2: **the watch floor** is the home view where every running line is visible; a **line** is one job (`/job/:id` is the line's floor: brief → crew → gate → landed); **the gate** is verifier + review + audit; **factories** are the configs a line is built from; **crew** are the roles; **shifts** are batches and overnight runs; **the tower** is compute; CLI stays `vigil` (`vigil floor` = one-screen status); the product name stays Vigil through G3; a master-brand decision is a card at G3 with a namespace check attached (GitHub, PyPI, npm, USPTO, domains); the daemon keeps the name `vigild` under any brand | Product decisions | **Adopt**; the two collisions ChatGPT cited (an orchestrator named Vigil; a "Watchfloor" agent-supervision deck) were not found on search and are unverified |
| R23 | Cache-miss rule for holds: per-task holds price prefix tokens the previous call reported as cache reads at the read rate (a miss may overshoot the task cap by at most one call's miss premium, recorded, paged, and the task's later holds price misses); day and month holds always price the prefix as a miss, so those caps stay hard; the prefix is counted from the previous call's reported usage, never estimated | Money and usage | **Adopt** (the per-task cap was never miss-proof since #215; this makes the bound explicit) |
| R24 | Subscription-backed workers: a `claude-sub` preset runs Claude Code in-container on the owner's Max plan through a headless token (`claude setup-token`) that **only the gateway holds** and injects; every call metered in tokens and booked against the weekly window (`usage_readings`, R5 lines count workers); holds and the task cap denominated in tokens for this preset; 429 = wait, not fail; `vigil doctor` checks expiry; never for a client repo; the scoreboard carries a window-share column so $/solved is honest. Spike first (experiment #24) | Models and routing | **Adopt as a spike** (owner 10-31: "keyless login would be huge"); the one harness it applies to is Claude Code |
| R25 | pstack (Lauren Tan, MIT, `cursor/plugins@4dd1d05`): borrow **methods, not the plugin**. vigild does the checking pstack asks the agent to do on itself: the decision trail becomes a contract field verified by vigild (p3-61); the verification-skill generator becomes how a repo gets its `verify/` CLI (p3-54); blast-radius's "one fact it's safe because of, proven by running code" becomes a reviewer output field (p3-06); `correct` becomes a scheduled job feeding R19 (p3-62). Adapted text is vendored with the MIT notice and pinned in `docs/sources.md`; the plugin is not installed in the executor image (ADR-0006); each packet addition ships with an eval case | Process | **Adopt** (owner 10-31) |
| R26 | Language policy: vigild stays Python (I/O-bound policy layer; correctness from Hypothesis property tests on budget and FSM invariants, typed models, replay); Rust is adopted as a **target stack Vigil builds** (p3-63), as the code-map engine only if the Python implementation fails measured latency targets, and for any component with a profiled bottleneck; no rewrite of the FSM, budgets, GitHub App, gateway or provenance; no embedding/vector store in any code-map v1 | Process | **Adopt** (owner 11-01; report `docs/research/rust-and-retrieval.md`) |
| R21 | Readiness profiles per repo (`mvp` / `production` / `enterprise`), modelled on SLSA levels and OpenSSF badges: `repos.yaml` carries the profile; it selects required verifier plug-ins (p3-54), `review.yaml` strictness, ladder caps and deploy targets; `vigil doctor` reports its checks; raising is a config PR, lowering is a ruling | Product decisions | **Adopt** as Track G's first row (owner 10-31: how it works, in §16) |

## 4. Gates

Work is grouped by gate. A gate's items may run in parallel subject to §9's
hot-file order; the next gate starts when the exit check passes, however
long that takes. Each item keeps its Vigil phase.

| Gate | Name | Exit check |
|---|---|---|
| G0 | Paper | PR 1a (docs) and PR 1b (rulings) merged; three check scripts exit 0; `docs/research/` committed with README |
| G1 | Landing | 10 consecutive Vigil PRs land with zero manual rebases and zero hand pushes to `vigil/*`; every merged PR's verdict is on its landed SHA; a planted overlapping task is refused at dispatch |
| G2 | Evidence | Reviewer packet shows the three JUnit sections; an `abort` lands as terminal with reward 0; the one metric reports on `/api/kpis`; lite-lane `gate_usd/build_usd < 1.0` for lite shapes; post-merge outcome KPI live; executor transcripts replay green |
| G3 | Cockpit | A brief goes advisor → owner → coord → report with no hand-copied text and relay time measured; a week of owner decisions made from `/` with no hand API calls; cards/day ≤10; both budget meters on one row; **30 product PRs merged through the full gate** (throughput gate; kill criterion checked) |
| G4 | Many factories, one gate | OpenCode passes phase 4's criterion; `factory_config` resolves routing tiers; routing shadow has ≥50 outcomes on one slice; experiment #19 (cheap-first cascade) and #21 (tower economics) have verdicts; #14/#15 spike verdicts recorded |
| G5 | Earned autonomy | Ladder ADR accepted; SPRT promotes one shape on planted defects; local grounded reviewer at rung 1 on one shape; replay eval runs weekly with k≥3 |
| Later | needs rulings | Track F greenfield, Track G graduation beyond R21, the room's lanes beyond approved cards, mobile |

## 5. Item register

Fields: id · feature-map slug(s) (existing row or new `docs/features/<slug>.md`) · ADR · issue · phase · gate · builder · tier (docs / code / pinned = `ladder_pinned_paths`) · deps · done_when (command → output) · migration step. Rows for every item are created in PR 1a with status `planned` and the item id.

### G0 Paper

- **p3-01 PR 1a (docs tier).** Commit this plan, six reports + `docs/research/README.md`; feature rows for every item below via `docs/features/<slug>.md`; `design.md` fixes (philosophy section with figures marked unverified; "Escalation forks full context" → fresh per ADR-0005; decision 20 $100 → $200; single-commit checkouts in the eval protocol; "Four ways to spawn" → shipped MCP tools; ParkAgent visibility note); `architecture.md` (line ~672 and `scheduler-fleet` → fresh; phase-2 "$5" → current; phase-3 section per §8); `ui.md` rewritten per §8 (page list, `/` Inbox spec, `$1.84 / $5.00` → `/ $25.00`, Langfuse → Phoenix, done-when); `docs/experiments/README.md` entries #14, #15, #18–#22; CLAUDE.md: one line pointing to the plan and the `gh run rerun` exception (≤200 lines). done_when: `uv run python scripts/check-feature-map.py && uv run python scripts/check-claude-md.py && uv run python scripts/check-docs-same-pr.py origin/main` → exit 0.
- **p3-02 PR 1b (pinned).** Lines R1–R21 in `docs/owner-rulings.md`; research don't-adopts merged into "## Not adopted" (one line each: Graphite/Aviator/Trunk/Mergify; LLM conflict auto-resolve without re-verify; `merge=union` on editable tables; agent self-merge; Chief-of-Staff dispatcher; Claude Tag/Duet as control plane; Bend proofs; comment ban wholesale; `openrouter/auto`; Droid/Warp CLI adapters; LLM judge). done_when: `uv run pytest tests/api/test_coord_token.py -k ruling -q` → passed (the tests of `vigild/jobs/rulings.py`); a coord citation of a new heading line resolves against the mirror.

### G1 Landing (the week's goal: no manual rebases)

- **p3-09 landing queue + rebase-on-land** (issue #172; rows `publish`, new `landing-queue`; tier pinned). vigild holds one landing mutex per repo (FIFO by approval time). In the vault: fetch main, rebase the `vigil/*` branch, regenerate generated files, run the verifier on the **rebased SHA** (base/before/after + hidden tests), record `verified_sha` on the job; green → force-with-lease push, wait for CI on that SHA, then the owner's squash merge is accepted only if PR head == `verified_sha` (the republish route #185 refuses otherwise). Red or a conflict in a leased logic file → `REWORK` with a fresh worker and the conflict context, plus an inbox card; conflicts only in generated files → regenerate and retry once. Staleness sweep: an approved-but-unlanded PR whose leased paths changed on main is re-rebased and re-verified before its card says "ready". Ends hand pushes to `vigil/*`. done_when: `uv run pytest tests/github/test_publish.py -k "rebase_reverify or sha_binding or stale" -q` → passed; a seeded conflict lands with a verdict on the rebased SHA; a PR whose head ≠ verified_sha is refused. LLM conflict resolution is never on this path (measured 55–65% agreement with developers' resolutions).
- **p3-05 scope leases** (rows new `scope-leases`; change `scheduler`, `wip-limit`, `kill-job`; ADR-0008; tier code). `scope_leases(task_id, globs, acquired_at, released_at, released_by, conflicts_with)`; acquired at dispatch, released on publish/abandon/kill/abort/verifier-unknown; dispatch refuses a task whose `scope_globs` overlap (strict `in_scope`) any unreleased lease across jobs, projects and configs; the job waits in `queued_scope` and the card names the holder. **Exclusive single-holder classes:** schema (`vigild/db.py`, R15), core (`runner.py`, `packets/assemble.py`, `fsm.py`). Generated artefacts can never be leased. done_when: `uv run pytest tests/jobs/test_scope_leases.py -q` → planted overlap refused with a page; kill releases; two schema tasks serialise.
- **p3-47 worker landing skill** (rows `task-packets`, `layer-1-claude-md`; tier pinned — packet text). The §7 text enters the worker packet as one skill file (pstack style: one principle per file); the verifier enforces the diff budget (R18): >400 changed lines excluding generated files → "split?" card. done_when: `uv run pytest tests/packets -k landing -q` → the packet carries the skill; `tests/test_verifier.py -k diff_budget` → an oversize diff files a card, not a verdict.
- **p3-48 generated tables are not worker-editable** (rows `docs-tables` (#211), tier code). CI fails if a worker's diff touches a generated table or `docs/architecture.md` tables directly; `.gitattributes merge=union` only for `docs/owner-rulings.md` and `CHANGELOG.md` (append-only), applied in the vault merge, never relied on at GitHub. done_when: `uv run python scripts/check-generated.py` → fails on a planted direct edit.
- **p3-07 abort outcome** (rows `job-state-machine`, `task-contract`, `worker-stop-hook`; FSM edge `building → aborted`, terminal, reward 0, no tamper flag; one sentence in `prompts/worker.md`; tier pinned). done_when: `uv run pytest tests/jobs/test_fsm.py -k abort tests/jobs/test_kill_followup.py tests/contract -q` → passed; schema export no drift.

### G2 Evidence

- **p3-03 ADR-0008 cockpit data model** (tier pinned): tables `briefs`, `decision_cards` (an index over `inbox_items`), `rulings_index` (cache of the file on main), `scope_leases`, `projects`, `usage_readings`; columns `jobs.brief_id`, `jobs.project_id`, `tasks.scope_globs`, `tasks.origin {vigil, foreign, bridged}`, `events.verifier_timings`. No `budget_ledger`. One migration step per table, appended last at its own merge under the schema lease. Fields in §11. done_when: `uv run pytest tests/test_db_migrate.py -q` → each step last-at-its-PR and idempotent; `uv run python -m vigild.contract.export` → no drift.
- **p3-06 reviewer evidence packet** (rows `reviewer`, `task-packets`, `finding-evidence-and-confidence`; tier pinned). Reviewer and auditor packets carry the verifier's JUnit diff, hidden-test categories, acceptance output and (when a repo has one) the `verify/` evidence bundle; `abstain` is a valid verdict that never counts as clean; mechanical gates resolve before any reviewer runs. **Safety fact (R25, pstack `blast-radius`):** the reviewer names the one fact the change is safe because of and the level it reached (1 said · 2 pointed at `file:line` · 3 walked the failure · 4 ran code · 5 reproduced in the app); a risk score above standard (p3-59) requires level ≥4 or the verdict is `abstain`. **PROMOTE rule (R19):** each finding tagged with the strongest layer that could have prevented it `{ARCH, LINT, SKILL, STYLE}`; a finding seen in ≥2 prior rulings emits `PROMOTE: <lint rule or type change>` as a brief card. done_when: `uv run pytest tests/packets/test_review_packet.py tests/review/test_review_stage.py -k "evidence or abstain or promote" -q` → passed.
- **p3-41 the one metric** (row `kpis`; tier code). `GET /api/kpis?window=30d` → `product_prs`, `usd_per_product_pr`, `owner_min_per_product_pr` (card answer + pinned-read time from events), `baseline_usd`, `baseline_min` (owner-entered from ≥10 comparable Claude-Projects tasks, experiment #20), `reverts_7d`, `manual_rebases`.
- **p3-42 lite lane** (R14; rows `auditor-and-trust-ladder`, `hidden-tests`, `budgets`; tier pinned). `configs/review.yaml` `lite_shapes`; scoreboard column `gate_usd/build_usd` per shape. done_when: a docs XS job runs verifier + review only; a money-path diff is never lite.
- **p3-44 post-merge outcome, read-only** (new row `post-merge-outcome`, split from the phase-6 row; tier code). Per merged PR: CI at 48 h and reverts within 30 days (`ci_test_result` trusts only `github-actions`, #206) as events and KPI; no fix jobs; a failed smoke on main opens a **revert PR as a card**, never a merge.
- **p3-08 verifier cache + flake quarantine** (row `verifier`, new `flake-quarantine`; tier pinned). Base run cached by (base SHA, `test_cmd`, dev-image digest); reruns up to `verifier.flake_reruns`; flippers quarantined with an audit row; "red = reject" only for deterministic failures. First case: `test_kill` flake of 2026-10-31. done_when: `uv run pytest tests/test_verifier.py -k "cache or flake" -q`.
- **p3-10 record-and-replay executor transcripts** (row `claude-executor`, new `executor-transcript-replay`; tier code). Redacted NDJSON fixtures replayed through a fake CLI; redaction test. done_when: `uv run pytest tests/executors/test_replay.py -q`.
- **p3-15 card instrumentation** (row `kpis`): `card_created`, `card_answered{via}`, `card_promoted`; cards/day, median time-to-answer, phone share. Decision delegation (owner, 2026-11-01; experiment #35):
  - every card carries its tier (A/B/C), the reason, and the recommender's confidence;
  - `card_answered` records how: `unchanged` | `edited` | `override`; a later reversal records `card_reversed` with a link;
  - a weekly finding lists each card kind with n, unchanged share and reversals. A kind with n ≥ 20, ≥ 95% unchanged and 0 reversals gets a ruling card proposing a promotion (C→B or B→A); a reversal demotes it automatically;
  - never promotable: merges, caps, secrets, App permissions, authority rulings, anything public or external (ParkAgent);
  - until G3, each tier-B decision coord makes goes in the morning report as one line (`decided: … · reversible by …`).
- **p3-49 executor model pinning** (rows `claude-executor`, `model-gateway`; tier pinned). `availableModels` = the session's preset, `enforceAvailableModels: true`, no `fallbackModel`; gateway refuses any model id not on the session token; records `requested_model` vs `served_model`. done_when: `uv run pytest tests/gateway -k served_model -q`; a container asking for another model is refused.
- **p3-21 retry packet** (rows `coord-loop`, `task-packets`; tier pinned): attempt 2 carries the prior diff, verifier output bounded to 6,000 chars, hidden-test categories; context fresh (R6).
- **p3-14 coord-session evidence** (Vigil job; row `training-data-firewall`, new `coord-session-evidence`): transcripts, `decisions.jsonl`, `approvals.md` through `redact()` as `provenance: claude` artefacts; exporter refuses (test); `evals/coord/` cases with controls; draft rulings lines; relay-time baseline for G3.
- **p3-50 context-budget telemetry** (§6; rows `task-packets`, `read-views`; tier code). Every assembled packet records tokens per layer, dropped items and the token budget hit, as an `events` row shown on `/job/:id`; the scoreboard reports tokens-before-first-tool-call per (shape, harness). done_when: `GET /api/tasks/{id}/events` shows `packet_assembled{layers:{...}, dropped:[...]}`.
- **Experiment #34, tool-pruned factory config** (after p3-50; runs under p3-23): the tools each (repo, shape) uses, computed from Phoenix traces, rendered by the factory config through a config PR the owner merges; tokens and $ per solved task against the current config. Also: failure → fix facts confirmed in ≥3 closed sessions become proposed layer-5 lessons, owner-approved (feeds #22).

- **p3-60 `claude-sub` preset** (R24; rows `model-gateway`, `budgets`, `router`, `claude-executor`, `usage-readings`; tier pinned — gateway, secrets). Experiment #24 first: mint a headless token, add the preset (`kind: anthropic`, `key_ref: CLAUDE_SUB_TOKEN`, `auth: bearer`, `locality: hosted`, `billing: window`), run one S job end to end; the threat tests prove the container never sees the token. Then: holds and the task cap in tokens against the weekly window (R23's logic, token-denominated); a window-headroom check at dispatch like #217's context check; 429 → queue; `vigil doctor` expiry check; `/budget`'s second meter reads it; scoreboard column `window_share`; never selected for a repo with `client: true`. done_when: `uv run pytest tests/gateway -k claude_sub tests/security -k token_not_in_container -q` → passed; one S job lands via `claude-sub` with $0.00 API spend and a recorded window delta.
- **p3-61 claims checked against the record** (R25, pstack `show-me-your-work`; rows `worker-stop-hook`, `task-contract`, `reviewer`; tier pinned — contract + reviewer packet). `worker_report.json` gains `decisions[]`: `{decision, why, evidence, result}`, where evidence is a typed pointer (`commit:<sha>`, `file:<path>:<line>`, `cmd:<id>` naming a command the session ran, `artifact:<path>`). vigild — never the worker — resolves every pointer against the bundle and the session's Phoenix trace: the SHA exists in the bundle, the line exists at that SHA, the command appears in the trace with the claimed exit code, the artifact exists. Unresolved or contradicted claims become findings at the severity of what they claim (a false "tests green" is high) and go into the reviewer packet beside the verifier's JUnit diff. This is pstack's "audit the log against the transcript", done by the host instead of by the agent on itself. done_when: `uv run pytest tests/review -k claims -q` → a report claiming `cmd:` exit 0 when the trace shows exit 1 yields a high finding; a pointer to a non-existent line yields a finding; a fully resolved trail yields none.
- **p3-62 `correct` as a scheduled job** (R25, R19; rows `improvement-proposals`, `automations`; tier code). Weekly (`configs/automations.yaml`): read the last 30 days of review findings, rulings, reverts and coord corrections; group into classes (a class = 2+ occurrences); for each, propose the highest-level fix (architecture → types → lint whose error names the fix → test → docs last) as a brief card with a check that **fails on a real past instance**. Never applies a change; output is cards. done_when: on this week's data it proposes at least the stale-PR-body and hand-push classes with failing-on-history checks.
- **p3-55 graceful landing** (rows `model-gateway`, `worker-stop-hook`, `budgets`; tier pinned — gateway + harness hooks). Each task's cap carries a landing reserve (config `landing_reserve_pct`, default 15). A `PreToolUse` hook in the container asks the gateway `GET /v1/budget` (session token; returns remaining work and landing $) and, once work spend crosses the line, blocks every tool except git commit and the report write with "budget low: commit what you have and write worker_report.json now". The hard stop at the cap is unchanged. Outcome `landed_partial` is reviewable, never auto-accepted. done_when: `uv run pytest tests/gateway -k landing tests/executors -k landing_hook -q` → a replayed session crossing the line ends with a commit and a report, spend ≤ cap.
- **p3-56 data-sized caps** (rows `budgets`, `factory-metrics`; tier code + configs PR). The scoreboard proposes `per_task` caps per (shape, size) = p95 of verified-job spend × 1.3, with N shown; a `configs/` draft PR the owner merges, re-proposed weekly; never applied automatically; never above the per-task hard ceiling in `budgets.yaml`.
- **p3-57 context ceiling + runaway detector** (rows `task-packets`, `claude-executor`, `factory-configs`; tier pinned — harness config). Per factory config: `context_ceiling_tokens` (compaction or a fresh session from the packet above it); runaway = N identical tool calls or no diff change across M calls → stop, page, outcome `runaway`. Measured with p3-50 (tokens per solved task before/after).

### G3 Cockpit

- **p3-04 brief flow on MCP** (row new `brief-flow`; change `mcp-server`; tier pinned). Brief FSM `{proposed → approved → delivered → superseded | rejected}`; `propose_brief` (advisor/admin, fenced); approval via existing `inbox_act(approve)`; `wait_for(job_id|brief_id, state, timeout_s)`. Surface tests: advisor approving → 403; coord approving → 403; no merge/cap/rung write.
- **p3-51 MCP facade for the Claude app** (R16; new row `mcp-facade`; tier pinned — auth). A separate process exposing `list_cards`, `get_card`, `job_status`, `budget_meters`, `rulings_search`, `propose_brief` over Streamable HTTP with OAuth (DCR), advisor scope only, rate-limited, through Tailscale Funnel :443; it proxies to vigild on the tailnet; never `inbox_act`. done_when: `uv run pytest tests/mcp_facade -q` → a call to any write tool but `propose_brief` → 403; a request without OAuth → 401; the facade holds no vigild admin token.
- **p3-52 the room in the UI** (R17; rows `session-proxy`, `bridge`, new `room`; tier pinned — it launches the coord session). `/talk` hosts two lanes on one chat component (borrowed MIT component, per the §17 research): the **coord lane** is a Claude Code session vigild launches via the Agent SDK with the coord token on stdin, streamed through the session proxy, restartable from records (p3-14's property); the **advisor lane** is any gateway preset with the facade's tools and the advisor scope; brief cards render inline; approval only in the Inbox. done_when: `uv run pytest tests/web -k room tests/jobs -k coord_sdk -q` → a brief proposed in the advisor lane appears as an inbox card with `author_scope: advisor`; killing and relaunching the coord lane loses no state; the advisor lane runs on an OpenRouter preset with Claude unavailable.
- **p3-58 standing brief classes** (R2; rows `brief-flow`, `inbox`; tier pinned — auth). `configs/briefs.yaml` `standing: [{class, max_usd, allowed_shapes, forbidden_paths}]`, each class created by an owner ruling card; a brief matching a class is auto-approved with the class named on the card and the same events as a manual approval; a brief outside every class waits for the owner. done_when: a research-only brief under $2 flows advisor → coord with no owner action and an `approved_by: standing:<class>` event; a brief naming a code path is held.
- **p3-59 risk score as a ladder input** (R18, R4; rows `merge-risk-grade`, `auditor-and-trust-ladder`, `scope-leases`; tier pinned). `vigild/jobs/risk.py` scores a diff from paths touched (money/auth/migrations/runner = max), churn of touched files (90 days), test coverage of touched lines where known, module-crossing count, and diff size; the score sets review depth (lite / standard / audit), lite-lane eligibility and auto-land eligibility; shown on the card and `/review`. The 400-line cap stays separate. done_when: `uv run pytest tests/jobs/test_risk.py -q` → a one-line change under `src/billing/` scores max; a 350-line docs change scores low; the score is on the PR body.
- **p3-17 pages per §8** (rows `web-ui`, `inbox`, `read-views`, `decision-cards`, `rulings-index`; every route gets a row; tier code). done_when: `uv run pytest tests/web -q`; each page <100 KB; a week of decisions from `/` with no hand API calls.
- **p3-18 metering endpoint** (`GET /api/metering`, `/metrics`; row `metering-endpoint`).
- **p3-19 scoreboard v0 + host-side scorers** (rows `factory-metrics`, `pareto-view`, new `host-side-scorers`): gates passed, findings by severity, $/solved, abort, trace-counted efficiency, tokens per solve, `failed_run`; keyed on (model, harness, prompt-template); no LLM judge.
- **p3-20 `review.yaml` change classes + `configs/automations.yaml`** (nightly audit, flag-expiry scan, deps intake, label intake; a schedule only files intake items; `uv run python -m vigild --check-config` → `ok`).
- **p3-13 project entity + cap** (row `projects`; change `budgets`, `model-gateway`; tier pinned): gateway refuses a reservation whose project cap is spent.
- **p3-46 issue-to-spec draft** (Vigil job; rows `spec-gate`, `task-synthesis` intake half): a labelled issue yields a `spec` card (test_cmd, done_when, scope globs, related tests from #141) within 10 minutes; never dispatched without approval.
- **p3-45 tower economics, experiment #21**: 20 S tasks × 3 runs, tower vs Sonnet, $/solved at measured watt-hours; decides rule 6's default (kill criterion).
- **p3-16 genesis spike** (by hand; `docs/research/genesis-spike.md`).
- **Throughput gate p3-43**: 30 product PRs merged through the full gate before G4.

### G4 Many factories, one gate

- **p3-22 OpenCode adapter** (phase 4; gateway OpenAI-compatible path shared with OpenRouter presets).
- **p3-23 `factory_config` as code** (`configs/factories/<name>.yaml`; per-harness policy rendering with a canary that every rendered file denies the same commands; row new `factory-configs`; tier pinned).
- **p3-36 shadow routing**, **p3-37 yardstick**, **p3-38 bounded decide**, **p3-39 harness in the choice set**, **p3-40 cheap-first cascade (experiment #19)** — §10.
- **Experiment #33, DeepSeek Harness (dsh) spike** (after p3-23; the shape of #14/#15): the Minimal profile keyless against the gateway, zero non-gateway hosts, telemetry off; if yes, a control arm for #25 and the Lab's harness comparison. Not a production worker before 1.0.
- **p3-11 harness spikes #14/#15** (experiment entries with smokescreen logs).
- **p3-12 public-PR task pool v0** (benchmark only; owner names 5–10 permissive repos per stack; ≥200 admitted tasks).
- **p3-63 Rust target stack** (R26; Track F's first row; rows new `stack-rust`, `verifier-plugins`, `dev-image`; tier pinned — images, verifier). Pinned-toolchain dev image (`rust-toolchain.toml`) with cargo-nextest, clippy, cargo-deny preinstalled; cargo-chef dependency layers per repo commit; a local-disk sccache volume mounted read-only in task containers; vendored crates or a local registry mirror (workers are no-egress); `CARGO_INCREMENTAL=0` in verifier runs; verifier adapter parsing nextest JUnit (`[profile.ci.junit]`, retries off), clippy JSON (new warnings vs base), cargo-deny (gate on any `Cargo.toml`/`Cargo.lock` change); cargo-mutants as a sampled audit (parse `outcomes.json`, never exit codes), miri only for crates with `unsafe`; templates: clap CLI, library crate with proptest, axum service, workspace, each with `#![forbid(unsafe_code)]` and a reproduction-test-first task rule; worker skill: `cargo check` in the inner loop, turns capped per error class. Its own replay slice (≥20 tasks × 3) before any ladder promotion; model Rust skill is benchmark-dependent (5–86% across 2026 sets), so only Vigil's numbers count. done_when: a Rust template repo lands one job through the full gate with nextest JUnit as the verifier's evidence and a cargo-deny gate exercised.
- **p3-25 cross-harness blind test-writing**; **p3-26 ask-gate + sizing** (#178, #175, flag `contract_gate` default off); **p3-27 chains** (cap 3); **p3-28 foreign-PR intake pilot**; **p3-29 security findings** (Semgrep/bandit as findings, never a gate); **p3-30 second seat** (#182).
- **p3-53 characterization-first refactor shape** (rows `task-contract`, `spec-gate`): a `refactor` shape dispatches a tests-only PR pinning current behaviour first (verifier confirms it passes on base), then the refactor.
- **p3-54 domain verifier plug-ins** (row `verifier`, new `verifier-plugins`; tier pinned): per-repo `verify/` CLI run by the verifier, never the worker; each repo's first `verify/` is produced by a Vigil job adapted from pstack's `create-verification-skill` (launch, doctor, drive, evidence, cleanup, a feature map of user journeys; the job is done only when the verifier has run it end to end once and the evidence survives cleanup) (SaaS: migration up/down on a fresh snapshot, CDP smoke with screenshots, API contract tests; automations: dry-run on recorded fixtures, idempotency by running twice; ML: data expectations, pinned dataset hash, held-out metric gate vs logged baseline; AI: frozen goldens, eval cost through the gateway). Evidence bundles attach to the card and the reviewer packet (p3-06).

### G5 Earned autonomy

- **p3-31 ladder ADR + SPRT** (p0 0.80, p1 0.95, α 0.05, β 0.10; tests land with the code; ADR-0002 for the merge identity before any auto-land per R4).
- **p3-32 local grounded reviewer at rung 1 + best-of-n** (ADR-0007).
- **p3-33 replay eval** (phase 7; k≥3; no LLM judge; experiments #13, #16, #17, #22).
- **p3-24 hidden-test admission + hackability audit** (L; after #153 and ADR-0003 a–d).
- **p3-34 self-edit job** (phase 7, Skill Doctor gate); **p3-35 E9 fine-tune** (≥300 local-provenance clean traces).

### Later (rulings needed)
Track F greenfield (stack templates, `vigil init`, executable-spec hidden tests, architecture tests, intent → chain planner, run-and-observe); Track G graduation beyond R21 (intake secret scan, oracles, deploy targets, evidence pack, product metrics); readiness check before rung >0 on any repo (strict types, lint as errors, generated-files manifest, migrations dir); the room's lanes; mobile (Inbox "Needs you" only).

## 6. Context engineering: where Vigil stands

What Vigil has (design "documentation standard"): an eight-layer tree with
one owner, trigger and CI check per layer; packets assembled per role with
a token budget per layer and a dropped-items log; a derived, uncommitted
code map (layer 7) rebuilt per commit; lessons (layer 5) tagged by path and
shape; fresh context for every stage, retry and reviewer; fenced untrusted
text; provenance on every packet; `ask_coord` as the one agent-to-agent
channel; harness thinning (ADR-0006). Against the field: Lauren Tan's
"codebase as memory, minimal context, clear process boundaries"; pstack's
"file pointers, not inlined context" and one-principle-per-skill; Grok
Bot's per-role separate memory; Cognition's single-threaded writes and
clean-context review; Anthropic's progressive disclosure. Vigil's design
already states all of these. What it lacks is **measurement** and three
specific inputs:

1. **Nobody knows what each layer buys.** The dropped-items log exists;
   no ablation does. → p3-50 telemetry now; experiments #17 (codemap in/out — design: arms A current packet, B + ≤1.5k-token structural map pre-injected, C map as a queryable tool only; tree-sitter symbols/callers/tests + BM25, commit-keyed, no embeddings; k=3 seeds; both tower and one Claude model; tasks pre-screened to drop those solved 3/3 or 0/3 by both arms; paired McNemar/Wilcoxon per stratum; adopt only if pass rate +≥5 pp at p<0.05, or non-inferior with ≥15% lower $/solved, with no regression on single-file tasks) and #22 (layer-5 lessons in/out) on the replay pool at G5; the
   scoreboard's tokens-before-first-tool-call per (shape, harness) is the
   standing number (OpenCode's startup prompt is ~7k tokens vs Claude
   Code's ~33k; that gap is a factory-config variable, not a constant).
2. **Run evidence is missing from packets.** Tests prove correctness of
   what tests cover; the fix-round packet carries only verifier text. →
   p3-54 `verify/` evidence bundles (traces, screenshots, logs collected by
   the verifier) reach the reviewer packet (p3-06) and the retry packet
   (p3-21) as file pointers, bounded.
3. **Roles are not boundary-explicit.** → R19: every role prompt (worker,
   reviewer, auditor, coord, advisor) opens with `owns / never /
   reports-to`; memory is scoped per role (the reviewer never sees the
   worker's transcript; the coord's memory is the job rows, rulings and
   `decisions.jsonl`, never a chat).
4. **The coord is the one place context is a transcript.** It `/compact`s
   and relays by paste. → the brief flow (p3-04) and the cockpit make the
   coord's inputs records (brief, rulings, cards) and its outputs records
   (reports on #1, `decisions.jsonl`); p3-14 turns its history into evals.
   The target: a coord session can be killed and restarted from records
   with no loss, which is the same property workers already have.
5. **Worker skills by shape.** The landing skill (§7) is the first;
   `prove-it-works`, `sequence-verifiable-units`, `subtract-before-you-add`,
   `separate-before-serializing-shared-state` (pstack, MIT) are adapted as
   one-file skills selected by task shape at packet assembly, each ≤40
   lines, each with an eval case before it ships (ADR-0006).

Verdict: the architecture is at the frontier on paper; the gap is that it
has never been measured, and p3-50 is the cheapest item in this plan.

## 7. Landing rules (worker skill text, verbatim)

```
LANDING RULES (Vigil worker)
- Touch only files inside your declared scope. If you need a file outside it, stop and write NEEDS_SCOPE: <path> <reason> in your report; do not edit it.
- Keep the diff under 400 changed lines excluding generated files. If the task needs more, deliver the first verifiable slice and list the rest under FOLLOW_UPS.
- Never edit generated tables (docs/feature-map.md, docs/architecture.md tables, any file with a GENERATED header). Add or edit your row file under docs/features/<slug>.md instead.
- Schema changes: append exactly one step at the end of MIGRATIONS in vigild/db.py; never edit or renumber an existing step. If another job holds the schema lease you will not be dispatched; do not work around it.
- Do not reformat, re-sort imports, rename or move code you were not asked to change. File drive-by cleanups as FOLLOW_UPS.
- Append-only files (docs/owner-rulings.md, CHANGELOG.md): add lines at the end of the relevant section; never reword existing lines.
- Do not merge or rebase main yourself. vigild does that.
```

## 8. The cockpit: `docs/ui.md` v2 (borrowed from T3 where it earns it)

**What to borrow from T3 Code** (free, MIT, 2,661 commits in two weeks —
the breadth is not borrowable by one person): its state vocabulary and
reversibility ("a one-way door is a bug": settle/snooze/pin each with a
reverse), `RunAttempt.reason` (Vigil adds `rebase_on_land`),
`limitRecovery {reset_at, auto_resume, snooze}` for subscription stalls
separate from dollar refusals, `approval_request` nodes with a `blocking`
bit, `olderSettled` counts, keyboard-first navigation. **What not to
borrow:** Full Access defaults, logins inside the harness, a general
multi-harness dashboard, more panes. The UI is exception-first for the
four things no one else has: the verifier verdict, the ladder, the dollar
stop, and the decision card with recommendation + override + "make it a
rule".

**Information hierarchy on every page:** (1) header strip — API $ today /
pacing / month, subscription window with `resets_at` or `unavailable`,
breakers, queue depth, WIP per repo, verifier wait; (2) **Needs you** —
typed cards, sticky, FIFO within kind, ordered page > breaker > brief/spec
> ready-to-merge > question; (3) **In flight** — one line per job grouped
by state; (4) **Settled** — counts only, expandable.

| Page | Content | Primary actions | Reads |
|---|---|---|---|
| `/` Inbox | levels 1–4 across projects | answer card `1–4`, `o` override, `r` make rule, `s` settle, `h` snooze, `u` undo | `GET /api/inbox`, `/api/tasks`, `/api/summary`, `/api/cards`; SSE `inbox`, `job`, `summary` |
| `/jobs` | today's Board table grouped by state; facets project, factory, origin | filter, open | `/api/jobs` |
| `/job/:id` | tree brief → coord → workers → reviewer → auditor; timeline; verdict; packet layers and dropped items (p3-50); evidence bundle; PR rail with diff; `verified_sha` vs head | kill, retry with reason, open on GitHub | `/api/tasks/{id}`, `/events` |
| `/review` | ready-to-merge queue: verdict first, findings by severity, diff stat, `verified_sha == head` badge; the ladder table (unchanged) | open on GitHub to merge | `/api/ladder`, `/api/review` |
| `/factories` | factory configs, scoreboard Pareto per (model, harness, template), rung per shape, decider calibration and labels (absorbs `/decider`) | propose config change (draft PR); label a decision | `/api/metrics`, `/api/decisions`, `/api/decider/calibration` |
| `/budget` | two meters on one row (API $ by gateway; subscription window by `usage_readings` with `stale_at`), per-task cost per triple, most-expensive list | — (caps change only by PR) | `/api/budget`, `/api/usage` |
| `/rulings` | every ruling with source card, status, draft PR, last cited | retire (draft PR) | `/api/rulings` |
| `/sessions` | live sessions, heartbeats, container IDs | kill | `/api/sessions` |
| `/talk` | advisor and coord threads with brief cards inline | propose brief (advisor); approval only in Inbox | as specified |
| `/watch` | unchanged | — | as specified |
| `/learn` | planned | — | — |

**Look v2 (owner, 10-31; reference image `docs/design/visual-identity-v2.png`, ChatGPT exploration).** Adopted as the brand direction: *Sonar* for the brand (point clouds, sweeps, reconstruction), *Watch Floor* for the product (cold control-room telemetry), *Industrial* for the world around it (factories, shifts, tower, docs imagery). North star: "Nothing moves unseen." What changes in `docs/ui.md` (PR 1a edits its Look section):

- **Mark:** the geometric V with a radar sweep replaces the character-drawn hat silhouette; it ships as an inline SVG (≤2 KB, two colours, legible at 16 px as the favicon and terminal icon). No literal bat anything.
- **Palette:** `--void #05080B` (page), `--graphite #121A22` (panels, hairlines at 30%), `--steel #364D61` (idle, borders, graph bodies), `--sonar #B8E7F8` (paler ice since 2026-11-01; detection, attention, the selected row, verification, live activity — used sparingly), `--signal #EAF6FC` (primary text), white only in the mark. Contrast is re-measured before the hexes are final (the warn pair `--signal` on `--steel` must pass AA at 12–13 px, as the 10-22 measurement did for the old pair); the rule *state is a word plus a glyph, never colour* stands, so the mock's BRIEF / CREW / GATE / LANDED chips are text in a hairline box, not coloured pills.
- **Type:** wide, tracked uppercase for the one heading per page; the monospace stack for everything that is data. Still no web fonts downloaded.
- **Imagery:** the renders live on the landing page, `/watch`'s ambient background and empty states only, served from the repo (never fetched), each ≤200 KB, with the page's data budget unchanged (<100 KB before images). Operational pages (`/`, `/jobs`, `/job/:id`, `/review`) stay flat: data first, atmosphere second. Further renders are generated as needed (ChatGPT is fine for source art; the repo keeps the files and their prompt).
- **Motion:** sonar pulse on a new line, a line scan on state change, a short acquisition on verification; nothing decorative, nothing looping.
- **Nav labels are the vocabulary, routes are R3's:** Watch Floor → `/`; Lines → `/jobs`; a line → `/job/:id`; The Gate → `/review`; Factories → `/factories`; Crew → `/sessions` (live crew) with role prompts linked; Shifts → `/jobs?shift=`; Tower → the tower panel on `/budget` and `/sessions`; Rulings and Talk keep their names. `vigil floor` prints the mock's terminal view.
- **Vocabulary → visual** (one language, each page its own character): watch floor = wall of live signals; line = a signal moving through checkpoints; brief = dossier; crew = assigned operators; gate = clearance checkpoint; landed = confirmed, archived; factories = blueprints; shifts = time-coded windows; tower = the mast.
- Namespace note for the G3 brand card: the exploration found "Vigil SOC" among unrelated projects using the name; the mark is kept adaptable to a later master brand while `vigil` and `vigild` stay.

**Decision card anatomy:** one-line question naming the blocker; two to
four options with the recommended one marked and a one-line rationale
carrying its confidence; free-text override; scope selector {this run,
this task, this factory, standing rule} where a standing rule opens a draft
PR to `docs/owner-rulings.md`; evidence links (verdict, diff stat, cost,
evidence bundle); auto-clear condition; `blocking` bit (a non-blocking
question lets the run continue). Batch cards from one brief ("approve 3
specs": approve all / review each). Card budget ≤10/day; a breach is a
weekly finding naming the ruling that would have prevented it.
Notifications only for pages, breakers and blocking cards older than 30
minutes; never on a finished turn.

**Navigation:** `g i/j/r/f/b/u` jump; `j/k` move; `Enter`/`Esc`; `/`
filter; `⌘K` palette over jobs, PRs, rulings, factories, commands
(including settled and archived; ambiguous IDs rejected); hover preview
cards instead of panes. **Density:** one line per job, ≤7 columns (id,
project, state glyph+word, blocker/next step, verdict, $ / window, age);
state is a word plus a glyph, never colour; "done" means the verifier's
verdict; numbers right-aligned, tabular, gateway-metered only. **Mobile:**
the Inbox "Needs you" level served responsively over Tailscale; never diff
review, merge, budget edits or secrets on the phone.

**One app.** Primary: ideate in the Claude app with the MCP facade
(p3-51: read + `propose_brief`), run coord in Claude Code with Remote
Control; approvals on the Inbox over the tailnet. Fallback when Claude is
unavailable, or for other people's stacks: the advisor lane in `/talk` (p3-52) on an
OpenRouter or tower model, same facade, same scope. Claude Duet (Oct 21,
Opus-only, waitlist, checks every few hours) and Claude Tag (Team/Enterprise
Slack) are not control planes.

## 9. Merge order and hot files

`db.py` (schema lease), `runner.py`, `packets/assemble.py`, `fsm.py` (core
lease). G0 → G1: p3-09 → p3-05 → p3-47 → p3-48 → p3-07. G2: p3-03 (one
PR per table) → p3-06 → p3-49 → p3-21; p3-41, p3-42, p3-44, p3-08, p3-10,
p3-15, p3-50, p3-14 off the hot files, in parallel. From G1 on, the landing
queue itself orders the rest.

## 10. Routing: rules decide, a proposer learns

Today: nine rules, first match wins, `tier_reason` named after the rule;
rule 2 refuses `--tier`; `live: false` presets fall back to Sonnet;
`check_backend` per call. Jev is a decider backend (typed `choice|score|bool`
with a probability, metered); it picks no model. `openrouter` preset exists
with `live: false`.

Evidence (report `docs/research/model-auto-routing.md`): prompt-only
routing on SWE-bench Verified reaches Route-AUC 0.627; after two cheap turns
0.780, and it broke across repositories; static classifiers fall to 9–21% on
OOD agentic tasks (random 31%) while outcome-fed bandits hold 46–50%; task
type explains ~27% of the oracle; most routers on LLMRouterBench fail to
beat always-best; the strongest chat model is the worst router. Cheap-first
pays when the cheap tier's verified pass rate exceeds the metered cost
ratio; a cheaper model running 1.9× longer costs more per solved task.
Harness choice moves pass rate 0–8 points (inside noise) but tokens per
solve up to 40×. Vendors: Warp's custom routers are ordered rules;
Copilot caps Auto candidates at ≤1× price; Bedrock routes to the cheapest
within a quality tolerance; OpenRouter `auto` ranks by community spend
share; Factory Router escalates "if the model struggles", detector
undisclosed; Vigil's detector is the verifier.

Design (R13): the router keeps the last word; a proposer chooses only
inside `allowed_presets(task)` (the rule's tier plus any tier the rules
accept as an override; rule 2 is a singleton); hard constraints never reach
it (money → Opus; private → listed backends; local session never hosted;
cap floor; `live: false`). Proposer = the decider's existing `tier`
question, inputs fenced, metered on `decider_call_usd`, every answer logged
`provenance: claude` beside the rule outcome; never a candidate model.

- **p3-36 shadow** (G4): action always `wait`; evidence row per slice
  `(repo, shape, size)` and arm `(preset, served model, harness pin, prompt
  revision)` with permitted set, metered tokens and $, wall time, tool
  calls, verdict, review rounds, attempt, `requested_model`/`served_model`.
  One model per attempt; escalation is a new attempt.
- **p3-40 cheap-first cascade, experiment #19** (G4, before any decide):
  rule-9 S tasks on one public repo, cheapest allowed preset first with
  `escalate_attempt: 2`, escalate on the verifier's failure; ≥9 runs per
  arm on the replay pool; if it wins, `cascade: [tower-qwen, claude-sonnet]`
  becomes the rule for that slice.
- **p3-37 yardstick** gates (all required; demotion on any): frozen replay
  set ≥20 tasks per slice run ≥3× per arm (a 2-point claim needs ~9 runs);
  ≥50 verifier outcomes per arm, no task counting >3; cheap arm's lower 95%
  Wilson bound exceeds metered cost_cheap/cost_strong by ≥10 points (tower
  floor 0.5); cascade pass rate within noise of the strong arm; Jev
  calibration ≥0.80 on ≥50 shadow answers at the 0.85 threshold; freshness
  (any model string, served model, price, harness pin or dev-image change
  demotes; re-run at 30 days). Demotion on a rolling 20-outcome window →
  rules-only + inbox item; p3-31's SPRT may replace the window.
- **p3-38 bounded decide**: `routing.yaml` `graduated: {<repo>/<shape>/<size>:
  {permitted: [...], cheap_first: true, expires_at: ...}}`, each graduation
  an owner-merged PR; decider policy reused (act ≥0.85, escalate ≥0.6, else
  the rule decides); kill switch `proposer.enabled: false`.
- **p3-39 harness in the choice set** (after p3-23): `choose_among` lists
  factory configs; graded on tokens per solve, wall time and failure
  fingerprint.
- **OpenRouter**: one metered preset per pinned model id with
  `provider.order`, `allow_fallbacks: false`, `zdr`, `data_collection:
  deny`, `require_parameters`, `max_price`; `models` fallback only among
  allowlisted presets with the served model recorded as the arm; never
  `openrouter/auto`. Decisions API with `typesafe/jev-1.13` for the decider.
- Out of the proposer's reach: the coord's, reviewer's and auditor's
  models; budgets. The early-abort question (Jev after two cheap turns) is
  deferred until #19 has data.

## 11. Data model appendix

All tables: `id TEXT PRIMARY KEY` with a prefix (`br-`, `dc-`, `ru-`,
`sl-`, `pj-`, `ur-`), `created_at` ISO UTC, `provenance` (PROV check),
free text through `redact()`.

| Table | Fields | Notes |
|---|---|---|
| `briefs` | id, project_id, author_scope {advisor, admin}, author_session, text (fenced), cited_rulings, proposed_jobs, state, approved_by/at, delivered_to/at, superseded_by | events per edge |
| `decision_cards` | id, inbox_item_id, kind {spec, brief, merge_ready, question, page, breaker, split, promote, revert}, options, recommended, rationale, confidence, override_text, scope, blocking, answered_via, answered_at, auto_clear_event | index over `inbox_items` |
| `rulings_index` | heading (PK), line_date, text, source_card_id, draft_pr, status | cache; the file on main wins |
| `scope_leases` | id, task_id, job_id, repo, globs, class {path, schema, core}, acquired_at, released_at, released_by, conflicts_with | unreleased indexed by repo |
| `projects` | id, repo, stack, prd_ref, milestones, envelope_usd, target_profile {mvp, production, enterprise}, training_allowed (default false) | FK from jobs |
| `usage_readings` | id, account, kind {session, weekly, monthly}, used_pct, resets_at, source {probe, manual}, read_at, stale_at | second meter |
| columns | `jobs.brief_id`, `jobs.project_id`, `jobs.verified_sha`, `jobs.landed_sha`, `tasks.scope_globs`, `tasks.origin {vigil, foreign, bridged}`, `tasks.shape`, `events.verifier_timings`, `events.packet_layers` | one step each |

## 12. API and scope appendix

Scopes: admin, read, heartbeat, coord, **advisor** (R2). The facade (p3-51)
holds only an advisor token.

| Route | Method | Scope | Row |
|---|---|---|---|
| `/api/briefs` | GET; POST (`propose_brief`) | read+; advisor/admin | brief-flow |
| `/api/inbox/{id}/approve` (existing) | POST | admin | inbox |
| `/api/wait` | GET long-poll | read+ | mcp-server |
| `/api/cards`, `/api/cards/{id}/answer` | GET; POST | read; admin | decision-cards |
| `/api/rulings`, `/api/rulings/{id}/draft` | GET; POST | admin | rulings-index |
| `/api/leases` | GET | read+ | scope-leases |
| `/api/projects` | GET; POST | read; admin | projects |
| `/api/usage` | GET; POST (manual) | read; admin | usage-readings |
| `/api/kpis`, `/api/metrics` | GET | read+ | kpis, factory-metrics |
| `/api/metering`, `/metrics` | GET | metrics token | metering-endpoint |
| `/api/landing` | GET (queue, `verified_sha` per PR) | read+ | landing-queue |

## 13. Security appendix

- Advisor scope: read + `propose_brief` + `wait_for`; never `inbox_act`;
  brief text fenced before coord reads it.
- Facade (R16): separate process, OAuth with DCR, Funnel :443, rate limit,
  advisor token only; vigild's API stays tailnet-only; approvals never
  cross the public path.
- Coord token: unchanged refusals; may re-run a PR's own failed check twice
  (10-31 ruling); may not approve or deliver briefs.
- Bridged executors (R1): separate OS account; bundle import only; public
  repos only.
- In-container foreign harnesses: binaries pinned in `docs/sources.md`;
  smokescreen log as evidence.
- Landing (p3-09): vigild is the only thing that rebases or pushes
  `vigil/*`; LLM conflict resolution never lands without the full verifier
  on the rebased SHA; the merge identity (ADR-0002) exists only at G5.
- Training (R20): `training_allowed` false by default; client code only to
  tower-local models; exclusion list; no cross-client models.

## 14. Research index (committed under `docs/research/`)

rust-and-retrieval (R26, p3-63, experiment #17's design; retrieval evidence: Cursor removed semantic search Aug 2026, structural index +8.5 pp within-harness but n.s. vs agentic grep, 214-run replication found no discriminating task); factory research Oct 2026 (R1–R8, E1–E11); Amp/Warp philosophy (A, W, V
items; don't-adopts); verification bottleneck and frontier techniques;
command-center landscape (data model, UX spec, roadmap — its phase numbers
are superseded by §4's gates); model auto-routing (§10); landing and
trust ladder (§7, §8, R15–R21; unverified items: the seven-role "Bot Team"
chart, the 60-bot post, the x.com link; Tan's Bend stance is "not her
path"). The README marks every report an unverified source; packet
assembly excludes the directory.

## 15. Migrations: the options (R15)

| Option | Strengths | Weaknesses | Verdict |
|---|---|---|---|
| (a) append-only `MIGRATIONS` list + schema lease + CI append-only check | zero dependencies; one file to read; matches CLAUDE.md; the lease makes collisions impossible rather than detectable | serialises every schema change through one lease; a lease outage blocks schema work | **Adopt now** |
| (b) one timestamped file per migration, runner applies in order, CI rejects two heads | parallel authoring; the git history is the migration history | ordering and head-detection code to write and test; two parallel schema changes still conflict semantically; more surface for a worker to get wrong | revisit if the lease blocks >1 job/week |
| (c) Alembic | mature tooling | needs SQLAlchemy, breaking "stdlib sqlite3 is the only DB layer"; a new dependency for no measured problem | never |

Data point: 19 migrations in ten days, never two in flight.

## 16. Readiness profiles: how they work (R21)

Models in the field, all ratchets: SLSA levels (1–4, each a strict superset; a build earns a level by passing its checks), OpenSSF Scorecard and Best Practices (passing / silver / gold), production-readiness reviews (a checklist gate before a service may take traffic), GitHub rulesets (required checks differ per branch). Vigil's version:

| Profile | Required at the gate | Deploy | Ladder |
|---|---|---|---|
| `mvp` | verifier (tests + lint), fresh-context review | preview only | rung ≤1 |
| `production` | + `verify/` evidence bundle (p3-54), flags on risky paths, post-merge watch + revert (p3-44), risk score (p3-59) on every PR | staging → prod by owner | per ladder |
| `enterprise` | + migration up/down dry-run, licence scan, SBOM, two-reviewer rule (second model family), characterization-first refactors (p3-53) | prod by owner, change record | per ladder, pinned paths rung 0 forever |

`repos.yaml` carries `profile`; `vigil doctor` reports the profile's checks; a config PR raises it; only a ruling lowers it. New repos start at `mvp`.

## 17. Open research (launched 2026-10-31, folds in when it lands)

R4 industry risk models and auto-land practice (Google/Meta/Uber review routing, time-to-revert as the metric, flag-gated landing); R7 Playwright-in-verifier-image vs raw CDP for a run-and-observe oracle; R17 whether T3 Code's chat components (MIT) are extractable or assistant-ui is the cleaner borrow, and the Agent SDK as the way vigild launches the coord lane on the owner's login; R18 what exists on GitHub for size/risk budgets (actions, Graphite, Meta's diff-risk); R21 the SLSA/OpenSSF mapping above, re-verified. None of these gates G0 or G1.

## 18. Rust future state: edges in Rust, centre in Python (R26)

Rust is adopted per component when its trigger fires, behind an interface that exists today and stays language-neutral (JSON over stdin/HTTP, versioned schemas; never Python objects). Tenancy ("multiple floors") is a data-model boundary first: `floor_id` beside `project_id` on rows and events (G3, with `projects`), per-floor data dirs, keys, budgets and repo lists.

| Component | Now | Rust form | Trigger |
|---|---|---|---|
| In-container worker runtime (stop hook, landing-reserve hook, PreToolUse budget check, claim capture) | Python scripts in the executor image | `vigil-hook`, one static binary with seccomp/Landlock; no Python in the session image | first non-Python target stack (p3-63) |
| Floor agent on other machines (tower, sandbox hosts, #51) | none | `vigild-floor`: runs containers remotely, enforces no-egress locally, streams events to the Mac control plane | the first second machine running workers |
| Gateway byte path (hold, meter, stream, redact) | Python | Rust proxy for the data path; Python keeps caps, routing, locality behind one call | >200 concurrent streams sustained, or measured p99 added latency >50 ms |
| Code-map engine (experiment #17) | Python + tree-sitter + SQLite FTS5 | tantivy behind the same API | p95 query >500 ms or cold build >60 s at 10k files |
| Verifier plug-ins (p3-54) | per-repo `verify/` CLIs | WASM plug-ins in a sandbox, one ABI across stacks | first third-party or client-supplied verifier |
| Event bus / UI fan-out | per-page SSE from vigild | Rust fan-out with per-floor filtering | more than a handful of simultaneous UI clients |
| Egress sidecar | smokescreen (Go) | unchanged | never |
| FSM, budgets, GitHub App, provenance, router | Python | Python | never |

Interfaces to keep language-neutral from G2 on: the per-session gateway token protocol; the hook protocol (JSON on stdin/stdout); the event schema; the code-map API (§14, rust-and-retrieval); the verdict schema verifier plug-ins emit; the claims pointer grammar (p3-61).

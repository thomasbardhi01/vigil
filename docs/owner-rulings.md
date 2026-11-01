# Owner rulings

The owner's decisions, one line each, newest first within each section. This
is an index. `CLAUDE.md` and the other docs are the binding text; when a line
here and a doc disagree, the doc wins and this line is stale. A ruling that
was replaced stays, marked `(superseded YYYY-MM-DD)`, with the new one above
it. Coord checks this file before asking the owner, and logs which ruling it
applied.

## Autonomy (what coord may do between the owner's windows)
- **2026-10-31** (R14): Lite lane: docs/lint/copy at XS/S on public repos skip audit and hidden tests; never money paths; rung-0 evidence only. **Ruling:** **Adopt**.
- **2026-10-31** (R12 backfill): Coord may approve a **replan** whose only changes are the fixes it names, citing the ruling, while every new spec and any card the owner has claimed is the owner's.
- **2026-10-31** (R12 backfill): Coord may re-run a PR's own failed check twice (`gh run rerun <id> --failed`, at most two per PR, after posting the evidence).
- **2026-10-30** (R12 backfill): A `repo_failures` failure that traces to a coord contract error counts as traced once the corrected replan's spec is approved; coord logs it as "contract error, replan <spec id>" and the reset is coord's.
- **2026-10-30** (R12 backfill): Coord resets a `wip` breaker when `GET /api/jobs` shows the repo below `wip_per_repo` at that moment (wip reset with room), logging the count.
- **2026-10-28** (superseded 2026-10-31 by R12: replan approval scope): Coord may approve a spec through MCP when the job is on the pre-approved list and the spec matches its brief and the owner's ACs. The list: the done-when batch (dw-62, dw-75, dw-38); the maintenance issues #98, #31, #79, #72, #71 and #102-#107; any replan of a job the owner already approved. Anything else, and anything touching money, auth, consent or a pinned path beyond those listed, waits for the owner.
- **2026-10-28**: Coord acts on pages by this file (retry, replan with a note, dismiss, rebuild, resume), and may reset a `repo_failures` breaker once it has named the three failures and traced each to a known issue. A page it can't trace waits for the owner.
- **2026-10-28**: Merges stay the owner's, in two windows: 08:00 and 20:00 ET. Coord marks PRs ready and orders work so nothing waits on a merge between windows; anything that needs a deploy is queued for the next window.
- **2026-10-28** (usage lines superseded 2026-10-31 by R5): Caps are the stop: $25 a day, $2 a task, WIP 4; usage lines 60% and 75% weekly.

## Merging and PRs
- **2026-10-31** (R4): Auto-land scope: Earned per (repo, shape) by the ladder (p3-31) **only after post-merge watch with auto-revert exists** (p3-44 grows a revert); the permanent never-list is money, auth, consent, migrations and pinned paths; deps and architecture leave the permanent list and are admitted only by ADR; review depth and eligibility read the risk score (p3-29); review-after-landing is reachable at the top rung, never below it; merge identity needs ADR-0002. **Ruling:** **Adopt** (owner 10-31: earn it, don't ban it).
- **2026-10-28**: Coord marks a PR ready on a clean review, not on green CI; auto-merge waits for CI.
- **2026-10-28**: Rebase a PR onto main only, never onto a branch still under review; a stack the owner set up is retargeted after its base merges.
- **2026-10-28**: The main ruleset requires a PR, squash only, the lint, types and test checks, linear history, no force pushes, and no bypass; "require up to date" is off (strict=false, checked through the API at 10:00) and auto-merge is on (#1).
- **2026-10-28**: Coord marks a PR ready and the owner runs `gh pr merge --squash --auto`; rebase only for a textual conflict (#1).
- **2026-10-28**: Merge tiers: docs-only or tests-only with green CI, the owner enables auto-merge on sight; code, the owner merges after a read; pinned paths, the owner reads the diff in person (#1).
- **2026-10-28**: One feature slice per PR, under about 600 lines changed, or split it before dispatch; the rule applies from the next dispatch, and #48, #49 and #58 merge as they are (#1).
- **2026-10-28**: A flaky required check is fixed deterministically (a fake clock or event, no longer timeout, no rerun plugin), with 20 consecutive local runs in the PR (#66).
- **2026-10-28**: Migrations: of two PRs that each add a step, the second to merge appends last; never insert a step before one production has run (#49).
- **2026-10-24**: The owner merges nothing until the focused review of a gateway, verifier or hidden-test PR is clean; the PR keeps `needs-review` until then (#19).

## Money and usage
- **2026-10-31** (R5): Usage lines. **Ruling:** **Pause new work at 85% weekly, stop at 92%**; page at $23/day, $20 overnight; supersedes the 10-28 line; the lines live in config and change by a ruling card, not by hand (owner 10-31: dynamic when needed).
- **2026-10-31** (R23): Cache-miss rule for holds: per-task holds price prefix tokens the previous call reported as cache reads at the read rate (a miss may overshoot the task cap by at most one call's miss premium, recorded, paged, and the task's later holds price misses); day and month holds always price the prefix as a miss, so those caps stay hard; the prefix is counted from the previous call's reported usage, never estimated. **Ruling:** **Adopt** (the per-task cap was never miss-proof since #215; this makes the bound explicit).
- **2026-10-28**: Caps: $25 a day (pacing only), $200 a month (the real budget), $2 a task (#88).
- **2026-10-28** (superseded 2026-10-28 by the line above): The daily cap is $10 for the phase 2 done-when run (#63).
- **2026-10-28** (superseded 2026-10-31 by R5): Coord asks for `/usage` only before a run longer than 2 hours, before an Opus worker, or when the last reading is more than 3 hours old; dispatch pauses at 60% weekly or 70% session, with a hard stop at 75% weekly (#1).
- **2026-10-28**: Unattended runs are allowed within the usage lines, after a /compact and with a short brief; the owner can stop them per run (#1).
- **2026-10-28** (superseded 2026-10-28 by the line above): No unattended runs until a spend guard exists (#1).
- **2026-10-27**: Experiment spend (bench) is a separate $30 monthly line, outside the day cap and inside the month cap, and a hard stop (#8).
- **2026-10-23**: Review and audit caps start at $0.40 and $0.80; the review reserve is held once per job when it enters review, and over-cap reviews complete with the overage charged to the daily cap (#1).
- **2026-10-23**: Fallback decider spend has its own $1/day cap with a breaker, and review and audit spend sits outside the per-task cap (#1).
- **2026-10-23**: The coord session cap is $2 and coord and worker output is capped at 16,384 tokens (#15).
- **2026-10-23**: Author spend for a flagged hidden-test task is capped at $1, outside the $2 task cap (#19).

## Models and routing
- **2026-10-31** (R1): Executor class: **one only** — keyless in-container against the gateway. A harness that cannot run that way is not a Vigil worker. Cursor stays the owner's IDE; Grok Build is decided by experiment #14; the bridged-executor design is retired and the gateway rule keeps no exception. **Ruling:** **Adopt** (owner 10-31: bridging was never needed).
- **2026-10-31** (R9): Codex/OpenAI. **Ruling:** When an OpenAI **API key** exists (owner: next month), Codex models join as presets on the OpenAI-compatible gateway path (p3-22); the Codex CLI is a harness only if it runs keyless against the gateway (experiment #23). A subscription alone cannot be used (R1).
- **2026-10-31** (R13): Routing proposer (§10): router keeps the last word; proposer narrows within allowed presets; shadow → yardstick → bounded decide per slice; `openrouter/auto` never. **Ruling:** **Adopt**.
- **2026-10-31** (R24): Subscription-backed workers: a `claude-sub` preset runs Claude Code in-container on the owner's Max plan through a headless token (`claude setup-token`) that **only the gateway holds** and injects; every call metered in tokens and booked against the weekly window (`usage_readings`, R5 lines count workers); holds and the task cap denominated in tokens for this preset; 429 = wait, not fail; `vigil doctor` checks expiry; never for a client repo; the scoreboard carries a window-share column so $/solved is honest. Spike first (experiment #24). **Ruling:** **Adopt as a spike** (owner 10-31: "keyless login would be huge"); the one harness it applies to is Claude Code.
- **2026-10-28**: Pin exception: llama.cpp b11739 (9 days old when adopted) is allowed until 2026-11-04, when the tower is rebuilt on a pin at least 14 days old (`docs/sources.md`) (#68).
- **2026-10-28**: Routing rule 3 fires on labels only; `architecture_paths` is removed (#61, #64).
- **2026-10-28**: Per-repo `ladder_pinned_paths` keep money-adjacent PRs at rung 0 with an Opus audit; `money_paths` and rule 2 are unchanged (#59).
- **2026-10-28**: Sonnet for delegated work, Opus for coord's own reviews (#1).
- **2026-10-28**: The tower serves Qwen3.6-35B-A3B for rule-6 workers (track C); the first tower-routed job is `vv-26`, with rung-0 Sonnet review and the Opus audit (#1).
- **2026-10-27** (superseded 2026-10-28 by the track C ruling above): Local models are for measurement only; no real job routes to local until the owner has seen the Smoke result (#11).
- **2026-10-23**: OpenRouter stays pinned to the Jev 1.13 model; a bump happens only by PR after the decider eval set is replayed, and a missing or different reported version counts as drift and falls back (#1).
- **2026-10-23**: The Jev route follows the repo's live GitHub visibility, checked at dispatch and before each OpenRouter call; a failed lookup counts as private (#1).
- **2026-10-23**: Coord uses Opus for rung 0, cross-module work and escalation; batch goes through the gateway (#1).

## Security and secrets
- **2026-10-31** (R2): `advisor` token scope: read + `propose_brief` + `wait_for` + `talk` (a non-binding lane coord reads as fenced text), never `inbox_act`. Work is dispatched only by a brief card; the owner may pre-approve a **standing brief class** (e.g. research-only, ≤$2, no code) under which briefs in that class flow advisor→coord without him, recorded like any approval. **Ruling:** **Adopt** (owner 10-31: "handles comms with coord unless I'm needed").
- **2026-10-31** (R16): Claude-app connector: a separate minimal MCP facade process (not vigild's API) exposed through Tailscale Funnel on :443 with OAuth, advisor scope only (read tools + `propose_brief`); approvals never on the public path. **Ruling:** **Adopt** with those limits; alternative is Remote Control only and no connector.
- **2026-10-31** (R20): Three tiers. **Eval** (running the factory against shipped code and scoring it; nothing redistributed): any public repo. **Training** a local model: permissive licences (MIT/Apache/BSD), the owner's own code, and consented code only; GPL/AGPL excluded. **Employer/client code**: `training_allowed` per repo default false, written consent, tower-local only, exclusion list, datasets out of git, no cross-client models. Opt the owner's GitHub account out of Copilot training. **Ruling:** **Adopt** (owner 10-31; not legal advice).
- **2026-10-28**: A session never opens a `.env` file or anything under `~/.config/vigil/`, even when the owner asks; the owner opens it in a Terminal of the owner's own (#1).
- **2026-10-26**: Hidden tests ship disabled by default; a flagged task opens an owner-review draft PR (#22).
- **2026-10-24**: Hidden tests are black-box (never import scope, base runner config, worker code only as a subprocess on a read-only checkout), and config overlaps are refused (#19).
- **2026-10-24**: Assertion failures carry an HMAC tag keyed by the host key, which the owner creates (#19).

## Repos (ParkAgent, visibility)
- **2026-10-31** (R10): ParkAgent. **Ruling:** Public now; after the flip tower-only; `repos.yaml` gains `tower-qwen` for ParkAgent **before any rule-6 job on it** (this is what unblocks product traffic).
- **2026-10-31** (restates the 10-28 line's standing parts): Coord may submit vigild jobs on thomasbardhi01/vigil; only the owner submits anything for ParkAgent; 'never submit' applies only to unattended runs unless the run's brief says otherwise (#1).
- **2026-10-28**: vigil stays public for now (rulesets and auto-merge need Pro on a private repo, Actions minutes, runner isolation); revisit after phase 2 with GitHub Pro and an isolated runner VM.
- **2026-10-28** (superseded 2026-10-31 by R12: replan approval scope): Coord may submit vigild jobs on `thomasbardhi01/vigil`; only the owner approves a spec out of `spec_pending`, and only the owner submits anything for ParkAgent; "never submit" applies only to unattended runs unless the run's brief says otherwise (#1).
- **2026-10-27**: Sandbox hosts are generic; code never names "the tower" (#43).
- **2026-10-24**: The private-repo hosted-model rule is waived for vigil only (hard-coded in `vigild/repos.py`) (#19).
- **2026-10-23**: ParkAgent stays public until 2a's reruns, the phase 1 run, the 2a merge and the allowlist cleanup (with doctor passing) are done; every repo is designed private-first (#1).

## Process (reviews, workers, reports)
- **2026-11-01** (R26): Language policy: vigild stays Python (I/O-bound policy layer; correctness from Hypothesis property tests on budget and FSM invariants, typed models, replay); Rust is adopted as a **target stack Vigil builds** (p3-63), as the code-map engine only if the Python implementation fails measured latency targets, and for any component with a profiled bottleneck; no rewrite of the FSM, budgets, GitHub App, gateway or provenance; no embedding/vector store in any code-map v1. **Ruling:** **Adopt** (owner 11-01; report `docs/research/rust-and-retrieval.md`).
- **2026-10-31** (R6): Retry context. **Ruling:** **Fresh** (ADR-0005); fork vs fresh = experiment #13.
- **2026-10-31** (R11): Plan and research location. **Ruling:** `docs/plans/phase-3.md`; reports under `docs/research/` with a README marking them unverified; `docs/research/**` excluded from packet layers.
- **2026-10-31** (R15): Migrations: keep `MIGRATIONS` as the append-only list (CLAUDE.md rule stands), add an exclusive **schema lease**, and a CI check that the list is append-only; timestamped files (Django/Alembic style) only if the lease blocks >1 job a week; Alembic never (needs SQLAlchemy). **Ruling:** **Keep the list + lease** (analysis in §15).
- **2026-10-31** (R18): Diff budget stays **fixed** (400 changed lines excluding generated files; per-shape values data-tuned later via p3-56); a **risk score** (p3-29, from paths touched, churn, coverage, module crossing) decides review depth, lite-lane and auto-land eligibility. Two knobs: the cap limits conflicts, the score limits risk; no dynamic threshold. **Ruling:** **Adopt** (owner 10-31: the variable is risk; industry ships fixed caps + stacking + risk scoring, not dynamic sizes).
- **2026-10-31** (R19): Reviewer PROMOTE rule and role `owns / never / reports-to` blocks in every role prompt (prompt change = PR with an eval run). **Ruling:** **Adopt**.
- **2026-10-31** (R25): pstack (Lauren Tan, MIT, `cursor/plugins@4dd1d05`): borrow **methods, not the plugin**. vigild does the checking pstack asks the agent to do on itself: the decision trail becomes a contract field verified by vigild (p3-61); the verification-skill generator becomes how a repo gets its `verify/` CLI (p3-54); blast-radius's "one fact it's safe because of, proven by running code" becomes a reviewer output field (p3-06); `correct` becomes a scheduled job feeding R19 (p3-62). Adapted text is vendored with the MIT notice and pinned in `docs/sources.md`; the plugin is not installed in the executor image (ADR-0006); each packet addition ships with an eval case. **Ruling:** **Adopt** (owner 10-31).
- **2026-10-29** (R12 backfill): The completion-integrity check (#104, PR #131) stays report-only for two weeks, until about 2026-11-12.
- **2026-10-28**: A routing rule's test submits a request through the API and checks the routed task; it never sets the input the rule reads (rule 6 never fired because `has_existing_tests` was never set while its tests set it by hand; #100).
- **2026-10-28**: After round 1, re-review only the new diff; a bug class found once is fixed everywhere in the PR; after two rounds, bring it to the owner (#1).
- **2026-10-28**: Coord checks `docs/owner-rulings.md` before asking the owner, and logs which ruling it applied (#1).
- **2026-10-28**: After #60 and backup (#23) merge, docs-, tests- and fix-shaped work on vigil is submitted as vigild jobs, not built by coord's subagents (#1).
- **2026-10-28**: Briefs say foreground only and no background jobs after the report; coord stops a worker that repeats or stalls for 20 minutes and finishes the step itself (#1).
- **2026-10-28**: Thresholds are pre-registered: the replay rule is fixed on pa-0003's 4 cases before a run, and a case whose status is not done is left out of recall (#49).
- **2026-10-26**: Review order is Sonnet first, Opus only for focused verifier, gateway and hidden-test reviews, at most 2 rounds, class-level text (#1).
- **2026-10-26**: At the round limit the owner may read the final diff in place of a further review (#28).

## Product decisions (per feature)
- **2026-11-01** (R27): The Lab: The Lab is Vigil's measurement surface: /learn, evals/, docs/experiments/, docs/research/. An experiment is a first-class row (question, hypothesis, metric from host-side scorers only, slice, arms as factory-config revisions, frozen admitted task set, k, budget line, pins, verdict, and the rule it would change; no rule it could change → refused at proposal). Experiments are proposed as brief cards, approved in the Inbox, run on p3-24-admitted tasks under their own budget line, and end in a card or a draft PR, never a merge or a rung change. No LLM judge. A Lab loop may auto-accept a revision onto its own branch only when all hold: score from the verifier and host-side scorers; metric continuous or yardstick thresholds met; accepted on a held-out split the loop never tuned on (--set heldout, disjoint from --set tune); change surface is one non-trust-path file or config value (skill ≤40 lines, one routing.yaml slice, one cap); revert exists. Verifier, gateway, review.yaml, hidden tests and the ladder never qualify. Paper now; table, runner and page at G4; self-edit and correct as proposers at G5. Vigild stays Python for it; Rust is the Lab's first non-Python subject via p3-63; an optional pure stats CLI may be Rust behind a JSON interface. Model-training curricula stay outside the repo.
- **2026-10-31** (R3): Page list replacing "nine pages and nothing else". **Ruling:** **Adopt §8's list**: `/` Inbox, `/jobs`, `/job/:id`, `/review`, `/factories` (absorbs `/decider`), `/budget`, `/rulings` (takes `/new`'s slot; `/new` becomes a palette command), `/sessions`, `/talk`, `/watch`; `/learn` planned. Eleven pages; no page merges.
- **2026-10-31** (R7): Browser oracle. **Ruling:** **Re-check pending** (research): lean is Playwright pinned by digest in the *verifier* image only (never the session image), CDP for traces/heap; decision 15's "no library" rule was about session-image weight.
- **2026-10-31** (R17): The room is in the UI: `/talk` hosts two lanes on one chat component — the **coord lane** is a Claude Code session vigild launches through the Agent SDK (the session-proxy row; subscription login still applies), so coord leaves the terminal; the **advisor lane** is any model through the gateway (Claude API, OpenRouter, tower) with the facade's tools. LibreChat is dropped. The Claude app stays the ideation surface via the facade (no API exists to mirror app chats). **Ruling:** **Adopt** (owner 10-31: baked into the UI, T3-like).
- **2026-10-31** (R21): Readiness profiles per repo (`mvp` / `production` / `enterprise`), modelled on SLSA levels and OpenSSF badges: `repos.yaml` carries the profile; it selects required verifier plug-ins (p3-54), `review.yaml` strictness, ladder caps and deploy targets; `vigil doctor` reports its checks; raising is a config PR, lowering is a ruling. **Ruling:** **Adopt** as Track G's first row (owner 10-31: how it works, in §16).
- **2026-10-31** (R22): Naming, v2: **the watch floor** is the home view where every running line is visible; a **line** is one job (`/job/:id` is the line's floor: brief → crew → gate → landed); **the gate** is verifier + review + audit; **factories** are the configs a line is built from; **crew** are the roles; **shifts** are batches and overnight runs; **the tower** is compute; CLI stays `vigil` (`vigil floor` = one-screen status); the product name stays Vigil through G3; a master-brand decision is a card at G3 with a namespace check attached (GitHub, PyPI, npm, USPTO, domains); the daemon keeps the name `vigild` under any brand. **Ruling:** **Adopt**; the two collisions ChatGPT cited (an orchestrator named Vigil; a "Watchfloor" agent-supervision deck) were not found on search and are unverified.
- **2026-10-31**: the backup destination is the tower over the rrsync-restricted key (#241, #248), with Time Machine on the Mac's 2 TB drive; #23 closes when a vigil restore from a tower set passes.
- **2026-10-28**: The lean coord packet ships behind `coord_packet` (default `classic`); the flip to `lean` is its own one-line PR carrying the spec-replay numbers for pa-0003 and vi-0002, merged on sight if both pass (#87).
- **2026-10-28**: Backup: the marker is a plain copy, doctor checks freshness at 36 hours, and the check is skipped only while the plist is not installed (#57).
- **2026-10-28** (superseded 2026-10-31 by the tower backup line above): `~/vigil-backups` is accepted as the interim backup destination until an external drive is attached; #23 closes when the first nightly set passes `vigil restore` (#23).
- **2026-10-28**: vigild runs under launchd so a reboot does not stop the factory; the plist sets `PATH` from a placeholder, and coord does the switch-over with the owner present (#65).
- **2026-10-28**: Kill follow-up is required before the done-when run: terminal states are final, sessions are marked killed, and no page or item opens on an abandoned job (#60).
- **2026-10-27**: Bench smoke results post as one vigild comment per vigil PR, updated in place, and never on ParkAgent or any other repo; the mix is 7 PolyBench TypeScript and 3 SWE-bench Pro tasks (#8).
- **2026-10-26**: The plan gate refuses a reused worker ID, and a job enters `in_review` only if every planned task has an open PR or is superseded (#25).
- **2026-10-23**: Job artifacts go to the vault, not the target repo (#30).

## Coordination (coord's own rules)
- **2026-10-30** (R12 backfill): `docs/owner-rulings.md` is a pinned path (`configs/repos.yaml` `ladder_pinned_paths`) (#146, #165).
- **2026-10-30** (R12 backfill): vigild reads the rulings from its mirror of origin/main, never from the checkout it runs from; a coord citation must contain one `## ` heading verbatim, and an unreadable mirror refuses (#146, #165).
- **2026-10-28**: Parallel tracks don't share hot files (`vigild/jobs/runner.py`, `vigild/packets/assemble.py`, `vigild/db.py` `MIGRATIONS`, or the same docs table); if they must, they run in sequence.
- **2026-10-28**: No stacked PRs unless the owner asks.
- **2026-10-28**: Coord's status holds one merge order; after each merge the next PR is rebased onto main and checked.
- **2026-10-28**: Coord assigns each migration-adding PR its step name at dispatch.
- **2026-10-28**: `scripts/check-all.sh` runs on the committed HEAD before every push, by workers and coord.
- **2026-10-28**: The long-term fix for docs table conflicts is #96 (one file per feature, generated tables).

## Not adopted (don't re-propose)
- **2026-11-01** (The Lab brief): Self-committing experiment loops onto main.
- **2026-11-01** (The Lab brief): An LLM judge for experiments.
- **2026-11-01** (The Lab brief): A home-grown harness as a worker.
- **2026-11-01** (The Lab brief): nanochat or model-training code in the repo before E9's trace threshold.
- **2026-11-01** (The Lab brief): A separate forge/ repo.
- **2026-11-01** (The Lab brief): A calendar for the Lab.
- **2026-11-01** (The Lab brief): The Lab's orchestration in Rust.
- **2026-10-31** (R8): ADR-0006 I exceptions. **Ruling:** **None now**; codemap stays an experiment; self-edit stays phase 7; worker-packet additions limited to the landing rules (§7) and one sentence each for `abort` and "fewest tests that fail on main".
- **2026-10-31** (research, phase-3 plan p3-02): Graphite, Aviator, Trunk or Mergify as the merge queue; vigild's own landing queue gives the invariant at this scale (`docs/research/landing-and-trust-ladder.md`).
- **2026-10-31** (research, phase-3 plan p3-02): LLM conflict auto-resolution that lands without the full verifier on the rebased SHA (measured ~55-65% agreement with developers).
- **2026-10-31** (research, phase-3 plan p3-02): `merge=union` on editable tables; only on append-only ledgers (`docs/owner-rulings.md`, `CHANGELOG.md`), applied in the vault.
- **2026-10-31** (research, phase-3 plan p3-02): Agent self-merge with review after landing below the top rung (R4).
- **2026-10-31** (research, phase-3 plan p3-02): A Chief-of-Staff agent that dispatches on its own; the Inbox is the only decision surface.
- **2026-10-31** (research, phase-3 plan p3-02): Claude Tag or Claude Duet as Vigil's control plane.
- **2026-10-31** (research, phase-3 plan p3-02): Bend LAWS/PROOF gates or other formal proofs in the verifier.
- **2026-10-31** (research, phase-3 plan p3-02): A wholesale comment ban in target repos; only workaround comments (TODO/HACK without a ticket), by lint.
- **2026-10-31** (research, phase-3 plan p3-02): `openrouter/auto` (or any vendor Auto mode) as a backend; OpenRouter is a pinned-model transport.
- **2026-10-31** (research, phase-3 plan p3-02): Factory Droid or Warp CLI adapters on current evidence (login and cloud requirements; routers unusable behind the gateway).
- **2026-10-31** (research, phase-3 plan p3-02): An LLM judge as a gate, a reward term or a routing reward; scorer names are host-side telemetry only.
- **2026-10-28** (ADR-0006 I): no multi-agent teams or debate; no memory or recall tools for workers; no LLM-generated instruction files and no longer CLAUDE.md (layer 3 is measured before it grows); no LLM-as-judge selection; no mid-trajectory critics; no RL on weights; no evolved verifiers; no more prompt text. The incident-to-playbook epic stays gated by replay.
- **2026-10-28** (omp / OMH research): neither project as a library or a layer; no inter-agent messaging bus (`ask_coord` stays the only channel: a single writer, read-only subagents); no fall-through model chains (the private-repo rule, budget predictability); no external memory server (one source of truth); no LLM-as-judge in rewards; omp's approval tiers never substitute for the guard plugin or the egress proxy; snapcompact, stream-abort rules, collab links and search providers are out of scope.

# Build the gate's cockpit, not another dashboard

Research cut-off 2026-10-30. Builds on `/home/claude/reports/Vigil factory research Oct 2026.md`, `/home/claude/reports/Amp and Warp philosophy for Vigil.md`, `/home/claude/reports/Verification bottleneck and frontier techniques.md` and the build list `/home/claude/reports/coord-prompt-post-phase-2.md` (items 1–23). Those findings are cited, not repeated.

**Bottom line.** The outer factory loop is now a commodity. Anthropic (Claude Code Projects, public beta) and Cursor (Projects, 10 Sep 2026) both ship a coordinator that does not write code and directs parallel workers, each worker opening its own PR ([Claude Projects](https://code.claude.com/docs/en/claude-projects.md); [Cursor](https://cursor.com/blog/projects)). GitHub shipped multi-repo Copilot projects and Agent Merge on 28 Oct ([GitHub](https://github.blog/news-insights/company-news/github-universe-2026-evolving-every-layer-of-the-stack/)). T3 Code gives the same command-center feel away for free, MIT-licensed, over six harnesses ([t3code](https://github.com/pingdotgg/t3code)). None of them ships four things: a verifier the worker cannot reach, an earned-autonomy ladder, a per-task hard dollar stop held by the only key holder, or a decision card that carries a recommendation and an override and can become a standing rule. So Vigil's Phase 3 UI should be an **exception-first cockpit for those four things and for the founder's advisor → command → operator loop**. It should not try to be a general multi-harness dashboard. The measured failures in this market argue the same way. They are integration failures: **27.67% of 107,026 open agent PRs already conflict with their base** ([AgenticFlict](https://arxiv.org/html/2604.03551v1)), and **two agents sharing files succeed about 50% less often than one** ([CooperBench](https://cooperbench.com/blog/curse-of-coordination)). They are attention failures: approval spam, measured at 25 prompts in one response ([openai/codex#10187](https://github.com/openai/codex/issues/10187)). Admission control, scope leases, rebase-and-re-verify on land, and rare typed cards address these. More panes do not. The weak parts of Vigil's thesis are the UI as a moat, harness breadth, and parallel factories on one repo. The strong part is the gate.

Evidence grades, used throughout: **[V]** = Verified, primary source read; **[R]** = Reported, secondary source; **[I]** = Inferred, my reasoning; **[U]** = Unknown, searched and not found. Product state is as read on 30 Oct 2026 unless a cell gives a date.

---

## 1. Executive decision memo

**Recommended path.** Phase 3 (the UI) should ship one global home: a sticky "Needs you" list of typed decision cards above a list of jobs grouped by state. Every row shows the verifier's verdict, and the header carries a two-meter budget strip. The data model behind it needs four objects the current design lacks:

- a **brief**: an advisor proposal that the owner approves and vigild delivers to coord, which ends the hand relay;
- a **decision card**: options, a recommendation, a free-text override and a scope;
- a **ruling**: a card answer promoted to `docs/owner-rulings.md` through a draft PR;
- a **budget ledger**: subscription windows and API dollars on the same run row.

Inside Vigil, keep one writer per scope. Make **scope leases** a dispatch-time refusal across every job, project and factory config. Add a harness only when it can run keyless behind the gateway (OpenCode, then Codex; Grok Build and Factory Droid after a spike). Treat Cursor Projects, Claude Projects and Copilot as **external factories**: their PRs enter Vigil's verifier and reviewer as untrusted input. Vigil never holds their credentials.

**Three biggest reasons**

1. **The labs are absorbing the outer loop and leaving the gate alone.** Cloud sessions, coordinators, routines, review tiers, CI babysitters and auto-merge are first-party and bundled. Every first-party gate is still an LLM reviewer, the repo's own CI, or a human [V] ([Claude changelog](https://code.claude.com/docs/en/changelog); [Agent Merge](https://github.blog/changelog/2026-10-28-agent-merge-watches-and-fixes-pull-requests-in-the-cloud/)). Agent PRs now merge *more* often than others (90% vs ≈86% within two weeks) [V] ([Octoverse](https://github.blog/news-insights/octoverse/octoverse-commits-pushes-reach-new-highs-in-2026-as-developers-build-with-agents/)). The vendors are optimising for throughput, not for gating.
2. **The measured failures are integration and attention, not missing features.** These are the conflict and cooperation numbers above, plus Organ's 61% of open agent PRs in conflict [V, self-reported] ([Organ](https://dev.to/itaisagi/ai-agent-pull-requests-stuck-in-merge-conflicts-what-broke-in-our-merge-path-and-what-we-changed-4ni9)) and a supervisable ceiling of 3–4 threads [R, opinion] ([Osmani](https://addyosmani.com/blog/cognitive-parallel-agents/)). A cockpit that adds sessions makes all of them worse. One that rations the founder's attention makes them better.
3. **The founder's slowest step has no shipped solution.** No surveyed tool ships a recommendation-plus-override card, and none shows subscription usage and API dollars on one row [V, absence across sources read]. Claude Projects' "remember the correction" and Warp's spec policy in foreman instructions are the nearest precedents for rule promotion [V] ([Claude Projects](https://code.claude.com/docs/en/claude-projects.md); [Warp](https://docs.warp.dev/factories/)).

**Three biggest risks**

1. **A lab closes the gate gap.** Factory Missions already writes a validation contract before code and uses validators that never saw the code [R] ([ZenML](https://zenml.io/llmops-database/multi-agent-software-development-system-with-extended-autonomous-execution)). A first-party "hidden tests in a fresh checkout" feature would erase the clearest differentiator.
2. **Vigil becomes approval spam with a nicer font.** If cards per day are not budgeted and measured, the cockpit recreates Codex #10187 for one person.
3. **Surface-area creep.** T3 Code landed 2,661 commits in the two weeks to 30 Oct [V] ([t3code commits](https://github.com/pingdotgg/t3code/commits/main)). A solo-built UI that competes on breadth loses, and every extra harness adapter is maintenance against vendor churn. Examples of churn: Gemini CLI withdrew individual service on 18 Jun 2026 [V] ([gemini-cli #27274](https://github.com/google-gemini/gemini-cli/discussions/27274)), and Cursor and Grok Build now sit under one owner.

**Next 30 days (to 29 Nov 2026)**

1. Land build-list items 1, 2, 4, 6, 7, 10 and 11 (Phase 0 below). The UI's verdict column, scoreboard and blocking waits read their outputs.
2. ADR: `brief`, `decision_card`, `ruling` and `budget_ledger` tables (new `MIGRATIONS` steps), plus `scope_lease` with a dispatch refusal on overlap. Each gets an FSM edge and an `events` row.
3. Revise `docs/ui.md`: `/` becomes the Inbox. The Board moves to `/jobs`. `/rulings` replaces `/decider`, which folds into Factories. Status vocabulary and the never-do list come from section 6. This needs an owner ruling because ui.md says "these nine pages, and nothing else".
4. Build the brief flow end to end on MCP before any pixels: advisor `propose_brief` → Inbox card → owner approve (phone) → coord receives it with cited rulings → `wait_for` returns coord's report to the advisor. Measure relay time before and after.
5. Spike Grok Build and Factory Droid in an egress-locked session image. Record the hosts each one tries in the smokescreen logs and whether its output stream carries token counts. Write one ADR per harness.
6. Instrument the attention budget now: cards created per day, median time to answer, the share answered from the phone, and the share promoted to rulings. Target ≤10 cards/day before Phase 1 ships.
7. Fix the stale envelope in the checkout. `configs/budgets.yaml` and `docs/ui.md` still read $5/day and $100/month; the owner's envelope is $25/day pacing, $2/task and $200/month (build-list item 1).

---

## 2. Assumptions and open questions

The brief's "How the founder works" section was blank. The assumptions below are what this engagement observed. Each lists the conclusions that depend on it.

| # | Assumption (observed) | Conclusions that depend on it |
|---|---|---|
| A1 | He plans with an advisor session (ideate, research, validate), then commands an operator session ("coord") that runs the factories, and wants to keep that split. Today he relays text between the two by hand, and the relay is the slowest step. | The `brief` object and its lineage (5.1); a Talk/brief view instead of a chat clone (6.2); exec memo reason 3; the Phase 0 brief flow. If he merged the roles, Claude Projects' single coordinator would serve him and Vigil's UI case weakens. |
| A2 | Decisions reach him as a/b/c option cards with a recommendation and a free-text override. He often answers from his phone, and often turns a one-off into a standing rule ("from now on"), which becomes `docs/owner-rulings.md`. | Decision-card anatomy and scope selector (6.3); `ruling` object (5.1); "Mobile, later" = cards only (8). |
| A3 | He reviews at the PR level and merges every PR himself, usually after the advisor has read the diff. He intervenes on exceptions (pages, budget lines, breakers), not by watching agents. | Exception-first home; no live-agent grid (6.6); the verdict as the primary PR fact; merge stays on GitHub. |
| A4 | He runs secret-bearing commands himself in his own Terminal. No agent ever holds his secrets. | External factories stay outside the trust boundary; subscription harnesses are not hosted in containers (5.4); the UI never asks for a secret. |
| A5 | He tracks two budgets: Claude subscription usage (advisor and coord sessions) and API dollars through Vigil's gateway ($25/day pacing, $200/month, $2/task). | The two-meter strip and `budget_ledger` (5.1, 6.1). If subscription usage cannot be read reliably, that meter shows `unavailable` (Q3). |
| A6 | He runs several projects: Vigil itself and ParkAgent, a private repo. He has access to Claude Code, Grok Build, Cursor, OpenCode, Codex and a local Qwen3.6-35B-A3B on a 2× RTX 5070 Ti tower. | Project facet, not project-first navigation (6.2); the private-repo constraint on external factories (5.4); harness order (8). |
| A7 | He likes T3 Code's command-center feel and wants a clean, minimal desktop/web UI where everything is findable. Mobile later. He wants it ambitious but rigorous. | Borrowing T3's state vocabulary (settle, snooze, usage windows) but not its breadth; keyboard-first; density rules (6.5). |

| # | Open question | Why it matters | How to settle |
|---|---|---|---|
| Q1 | Budget envelope: the local checkout's `configs/budgets.yaml` reads $5/day, $2/task, $100/month, and `docs/ui.md` shows `$1.84 / $5.00`. The owner's stated envelope is $25/day pacing and $200/month. | The header strip and breakers must show the real caps. | Build-list item 1 records the real envelope; check `main`, since this checkout may be stale (it also has no `docs/owner-rulings.md`). |
| Q2 | ParkAgent's visibility: the `design.md` example YAML marks it `public`; the owner calls it private. | Decides whether hosted external factories may touch it at all. | Owner ruling; `repos.yaml` on main. |
| Q3 | Can Vigil read Claude subscription usage for the advisor and coord sessions? No official usage API was found [U]. T3 Code probes for it and models `unavailable {unsupported, probeFailed}` [V] ([providerUsageLimits.ts](https://github.com/pingdotgg/t3code/blob/main/packages/contracts/src/providerUsageLimits.ts)). | Without it, the two-budget display is half manual. | Phase 0 spike; fall back to owner-entered readings with a staleness stamp. |
| Q4 | Does Grok Build run keyless against a custom `base_url` with no xAI sign-in? Gateway vendors document per-model `base_url` + `env_key` [R] ([Orq.ai](https://docs.orq.ai/docs/integrations/code-assistants/grok-build)); the launch page says "sign in with your account" [V] ([x.ai](https://x.ai/news/grok-build-cli)). | Decides whether Grok Build is a worker or only an external factory. | Egress-locked spike. |
| Q5 | Does Factory `droid exec` with BYOK phone home? Air-gapped mode is Enterprise-only [R] ([Latent Space wiki](https://latent.space/wiki/factory-ai-198fea7c/)). | Same as Q4. | Same spike. |
| Q6 | Does the owner want foreign-PR intake (Vigil verifies PRs that Claude/Cursor/Copilot factories open)? | It is the main way his non-keyless tools join Vigil. | Owner ruling; pilot on `thomasbardhi01/vigil`, where `anthropic` is already allowed. |
| Q7 | Will the advisor (a claude.ai or Claude Code session) be allowed to *propose* briefs through `vigil mcp`? Proposing is not approving. | The relay fix depends on it. | Owner ruling; MCP surface test (build-list item 11) asserts `propose_brief` cannot approve. |

---

## 3. Landscape matrix

Each cell carries its grade. "Learn / avoid" cells are [I] unless marked.

**3a. First-party and funded factories**

| Product | Surface | Orchestration model | Multi-project | PR coherence mechanisms | Pricing (Oct 2026) | Maturity | Vigil: learn / avoid |
|---|---|---|---|---|---|---|---|
| Claude Code (Anthropic) | CLI, desktop, web, mobile Code tab, Slack (Claude Tag) [V] | Cloud VM per session; `--cloud` fan-out; Projects = coordinator + worker threads; subagents, `pipeline()/parallel()`; routines on cron/webhook [V] | Projects span repos, one thread+PR per repo; 200 new threads/day; thread limit "isn't a hard cap" [V] | Auto-fix CI and comments (cannot see conflicts, "no webhook"); review tiers; Resolve conflicts / Fix CI / Merge it buttons [V] | Against plan usage; routines 5/15/25 runs/day [V] | Cloud GA; Projects beta [V] | Learn: GitHub proxy keeps credentials outside the VM, six state groups. Avoid: auto-fix pushes when a fix "is clear", so the worker judges itself |
| Cursor (now SpaceX) | IDE, Agents Window, web, iOS remote control, `agent` CLI, Agent SDK [V] | Local worktree + cloud agents; Projects coordinator "doesn't write code itself"; SDK agents on PR/Slack/webhook/cron [V] | Cloud envs up to 300 repos [V] | Bugbot, Security Review, "follow your PRs, fix CI", Rollouts [V]; merge block opt-in, default off [R] | Free / Plus $8 (Grok-only, includes Grok Build) / Premium $30 / Super $100 / Ultra $200; pool shared with Grok [V] | GA; Projects beta [V] | Learn: SDK "agent as code folder + evals". Avoid: "merge 6× as many PRs" as the success metric. Headless needs a vendor key, so not a keyless worker [V, prior report] |
| OpenAI Codex | CLI, IDE, macOS app, web, Python SDK [R] | Cloud task per workspace; app-server JSON-RPC (Thread/Turn/Item) under every surface [R] | Reusable cloud envs [R] | Automatic cloud reviews post to PRs; PR creation manual [R] | Plan tiers with per-5h ranges; page looks stale [V, stale] | GA [R] | Learn: `acceptWithExecpolicyAmendment`, i.e. "approve and make it policy". Avoid: Guardian subagent auto-approving |
| GitHub Copilot cloud agent | github.com, agents panel, Copilot app, VS Code, CLI, mobile [V] | Issue → Actions env → draft PR; Copilot projects (multi-repo); automations [V] | Multi-repo projects (28 Oct) [V] | Actions don't run on agent pushes until a human approves; Agent Merge + auto-merge [V] | Pro $10 / Pro+ $39 / Max $100 / Business $19; AI credits with org budgets [V] | Agent GA; projects new [V] | Learn: the CI-approval gate. Avoid: Agent Merge, which removes the human from merge. The nearest 18-month threat [I] |
| Grok Build (xAI/SpaceX) | Terminal CLI; ACP for front-ends [V] | Parallel subagents with own worktrees; `-p` headless [V] | None described [U] | None (no cloud, no PR) [V, absence] | SuperGrok/X Premium+; inside Cursor Plus $8 [V] | Early beta May 2026 [V]; "1.0 on 7 Aug" per one secondary source [R], conflict unresolved | Worker candidate if keyless (Q4). Sandbox off by default; reads Claude hooks but ignores `permissionDecision` [R] ([ACP](https://agenticcontrolplane.com/controls/grok-build)) |
| Google Antigravity / Jules | Antigravity 2.0 desktop, CLI, SDK, API; Jules web [V/R] | Dynamic subagents, async tasks, cron Scheduled Tasks, `/goal` [V] | [U] | No PR flow in the 2.0 post [V]; Jules V2 waitlist [R] | No 2.0 pricing [U] | Shipped 19 May 2026; current state weakly verified | Avoid: depending on an individual-tier CLI (Gemini CLI cutoff) |
| Devin (Cognition) | Desktop (ex-Windsurf, kanban "Agent Command Center"), Cloud, CLI, Review [V] | Parent/child sessions, session tree; drives Codex/Claude/OpenCode via ACP [V/R] | Spaces [V] | Devin Review per commit; 22.85% of Devin PRs conflict [V] | Free/$20/$200; Teams $80 + $40/seat [R] | GA [V] | Learn: `max_acu_limit`, `out_of_credits` state, named blockers. Avoid: hosted brain, "internet access strongly recommended" [V] |
| Factory (Droids, Missions) | CLI (`droid exec`), desktop, web, IDE/ACP [R] | Missions: orchestrator writes a validation contract first; serial fresh-context workers; validators that never saw the code [R] | [U] | Contract + serial execution + per-feature review agents [R] | Pro $20 / Plus $100 / Max $200 / Teams $60 + $40 [R] | $5B, Missions Apr 2026 [R] | Closest design to Vigil. Learn: contract-first, blind validators, serial by default. Avoid: validators inside the same run [I] |
| Amp | CLI, desktop, iOS/Android, orbs [V/R] | Threads; self-hosted orbs dial out to ampcode.com; Linear assign; PR follow-up into the thread [V/R] | Multi-repo projects (Aug) [R] | PR follow-up loop; no PR culture internally [R] | Usage; self-hosted orbs free for non-enterprise [V] | Fast cadence [R] | Learn: spawn/pause/delete dispatch contract. Avoid: the orb phones home |
| Warp Factories / Oz | Terminal, Agent CLI, cloud factories [V] | factory.yaml; foreman + triage/spec/implement/review/verify agents; scorers [V] | Team-wide Runs and Inbox [V] | "Never merges on your behalf"; review agent "doesn't approve or merge" [V] | PAYG +20%, Build $20, Business $50/user; Enterprise self-hosted workers [V] | Early Access [V] | Learn: global Inbox, "Cost per PR, an estimate, not an invoice". Avoid: transcript scorers as a gate (prior report) |

**3b. Independent control surfaces and self-hosted factories**

| Product | Surface | Orchestration model | Multi-project | PR coherence | Pricing | Maturity | Vigil: learn / avoid |
|---|---|---|---|---|---|---|---|
| T3 Code | Local server + web, desktop, iOS/Android [V] | environment → project → thread → run → attempt; delegate to linked environments; ACP [V] | One global snapshot, threads grouped by project and environment; multi-repo review [V] | `pullRequests[]` per thread; no merge queue or cross-thread conflict check in recent commits [V] | Free, MIT, "selling… Nothing" [V] | 0.1.0 on 15 Oct; very active [V] | Learn: settle/snooze/pin with reverse states, `limitRecovery`, usage windows. Avoid: Full Access default, logins inside the harness |
| Conductor | Mac app, cloud (Vercel sandboxes), iOS, API + MCP [V] | Workspace = worktree + env, BYO CLI agents [V] | Multi-repo cloud workspaces [V] | Blocks merge if the PR changed since the workspace was built; stack PRs [V] | Free / Pro $50 / Teams $60/user [V] | Weekly releases [V] | Learn: stale-head merge refusal. Avoid: "local agents run without sandboxing" [V] |
| Sculptor (Imbue) | Desktop Mac/Linux [V] | Workspace copy, agent tabs share one copy, "stagger them" [V] | [U] | Create PR via `gh`, inline checks [V] | MIT [V] | Research preview [V] | Learn: fix-bug skill writes failing tests first |
| Emdash (YC W26) | Desktop all OSes, SSH remotes [V] | Worktree per task, best-of-N [V/R] | Many trackers [V] | Diff, PR, CI, merge in one place [V] | Apache-2.0; cloud unpriced [V/R] | Active [V] | Avoid: writing hooks into the user's agent config |
| Paradev (ex-Superset) | macOS desktop, iOS (Pro) [V] | Worktree + terminals per task [V] | [U] | PR pane; send diff lines to the agent [V] | Free desktop; Pro [U] | Active, ELv2 [V] | Learn: diff-line feedback to the run |
| Cline (+ Kanban) | IDE, CLI, desktop, SDK [V]; Kanban web [R] | Card = terminal + worktree; **dependency chains** [R] | [U] | Agent resolves conflicts on commit [R] | Free [R] | Active [V] | Learn: chains. Avoid: agent-resolved conflicts with no re-verification |
| Kilo Code (Anaconda) | VS Code, JetBrains, CLI, cloud [V] | Agent Manager, managed worktrees, up to 4 variants [V] | Multi-project panel; rejects ambiguous IDs [V] | Refuses merge if the head changed; auto-merge [V] | MIT; 0% gateway markup [R] | Active [V] | Learn: ambiguous-ID rejection, PR badge states |
| Zed | Editor; Threads sidebar [V] | Zed/ACP/terminal threads; worktree per thread [V] | Grouped by project [V] | None: "your normal Git workflow" [V] | Free/Pro $10 [R] | Active [V] | Learn: archive frees the worktree; ACP Registry |
| OpenHands | OSS canvas, cloud, enterprise self-host [V] | Conversations + container sandboxes [V] | Many SCMs [V] | None specific [V] | Free MIT / Teams $500 for 10 / Enterprise [V] | Mature [V] | Price anchor: Vigil competes with the free tier |
| Tembo | Web, Slack, Linear [R] | Runs others' agents in VMs [R] | Multi-repo PRs [R] | Feedback loop from PR comments [R] | $60/$200 [R] | Active [R] | Closest neutral positioning |
| Ona (ex-Gitpod) | Web, automations [R] | Trigger + script + prompt [R] | Org-wide [R] | Small daily PRs, some auto-merged [R] | [U] | Active [R] | Precedent for narrow auto-land classes |

**3c. Review and merge tooling**

| Product | Model | Pricing | Note for Vigil |
|---|---|---|---|
| Graphite (Cursor-owned since Dec 2025) | Stacks, merge queue, PR inbox capped at 3/30 repos [V/R] | $20–$50/user [R] | Learn: a bounded repo set and inbox sections ([inbox](https://graphite.com/docs/use-pr-inbox)) |
| CodeRabbit / Greptile / Qodo | Review agents with rule files [V/R] | $24–$72/dev; $30 + credits; $30 base + credits [R] | A second meter outside the gateway; hosted review breaks the private-repo rule [I] |
| Macroscope | Check-run agents as blocking checks; Murmur (beta) orchestration [V] | [U] | A review vendor moving into factories |
| Linear (agents) | `AgentSession` states pending/active/error/awaitingInput/complete/stale [V] | — | Status vocabulary; no blocked-by gating of delegation [V] |

**3d. Defunct, sunset or absorbed (verified)**: Terragon (shutdown snapshot 16 Jan 2026) [V] ([repo](https://github.com/terragon-labs/terragon-oss)); Crystal (deprecated Feb 2026, now Nimbalyst) [V] ([repo](https://github.com/stravu/crystal)); Roo Code (sunset 15 May 2026) [V] ([repo](https://github.com/RooCodeInc/Roo-Code)); Vibe Kanban's company (shutdown announced 10 Apr 2026, OSS still committed to on 28 Oct) [V] ([post](https://vibekanban.com/blog/shutdown)); Codegen standalone (discontinued 9 Jan 2026, absorbed by ClickUp) [V] ([Codegen](https://codegen.com/an-update-on-codegen/)); Gemini CLI for individuals (18 Jun 2026) [V]. Bloop gave the reason in its own words: "thousands of daily users are free users" and no business model.

---

## 4. Deep findings

### 4.1 Coherence comes from scheduling and re-verification, not from shared context

The industry's main coherence mechanism, a shared instruction file, has the weakest evidence. `AGENTS.md` is read natively by Codex, Cursor, Copilot, Devin, Zed, Warp, Jules and others. Claude Code reads `CLAUDE.md`, and whether it falls back to a bare `AGENTS.md` is disputed between a widely shared gist and a later survey [V gist / R survey] ([gist](https://gist.github.com/yurukusa/d36197848911f025add142abefcde685); [Vaughan](https://codex.danielvaughan.com/2026/05/27/agent-instruction-files-agents-md-claude-md-cross-tool-portability-codex-cli/)). Precedence, nesting, size caps and import syntax differ per harness, so six factory configs reading one repo see six different effective contexts [I]. The one 2026 paper that found a benefit measured efficiency, not quality: −28.6% median wall-clock and −20.1% output tokens for Codex on 124 small PRs [V] ([arXiv 2601.20404](https://arxiv.org/html/2601.20404v2)). The outcome-level ablations found no accuracy gain, and found 66.7% adherence to a single checkable rule (prior reports). **No study measures whether two agents given the same file produce convention-consistent code** [U]. That absence is the disconfirming evidence for "coherence through shared context".

Spec-driven workflows help procedurally, not across parallel work. Warp's PRODUCT.md/TECH.md skills, Spec Kit, Kiro and Tessl are all sequential and per feature. The one controlled study found +0.15 judge points at +55% latency, and humans mostly scored the two arms a tie [V] ([arXiv 2604.05278](https://arxiv.org/html/2604.05278v1)). Kiro alone builds a task graph and runs independent tasks "in waves" [V] ([Kiro](https://kiro.dev/docs/specs/best-practices/)). Warp's list of checkable **product invariants** is the piece worth taking [V] ([Warp](https://www.warp.dev/blog/three-skills-for-spec-driven-development)).

The evidence that does exist points at scheduling:

- **CooperBench.** Two agents building compatible features on the same files reach about 25% success, roughly 50% below one agent doing both. 63% of failures were "expectation" failures: the agent heard the partner's plan and ignored it. Successful runs claimed files before coding [V] ([CooperBench](https://cooperbench.com/blog/curse-of-coordination)).
- **AgenticFlict.** Conflict rises with churn and plateaus near 32% [V].
- **Organ.** Merge-path fixes raised merges from 68 to 112 a week, but "shared-file collisions continued" [V].
- **Developers Digest (219 PRs in a day).** The failures were at the host: shared checkouts, a `pkill` that killed other agents' builds, a full disk, and zero-diff PRs logged as successes [V] ([Developers Digest](https://www.developersdigest.tech/blog/parallel-agent-fanout-day)).
- **Merge queues are downstream.** 94% of private merges go one at a time, and whole-PR agents are "a rounding error" [V] ([Mergify](https://mergify.com/reports/state-of-merge-queues-2026)).
- **Pre-merge overlap detection is unadopted** (GitHub OSPO's detector, 4 stars) [V] ([repo](https://github.com/github-community-projects/pr-conflict-detector)).

Policy does not port either. Each harness has its own policy file, most hooks fail open, and none controls egress [R] ([Failproof AI](https://befailproof.ai/ai-coding-agent-admin/managed-policy-files-for-every-coding-agent/)). OpenCode has no sandbox [V] ([OpenCode](https://opencode.ai/v2/docs/permissions/)). Review agents can block on rule files [V] ([Macroscope](https://macroscope.com/blog/introducing-check-run-agents)), but no vendor publishes a convention catch rate. The one independent bug benchmark puts F1 at 51–60% on 50 PRs [R] ([compilation](https://gitautoreview.com/blog/ai-code-review-benchmark-2026)). **No tool detects cross-PR duplicates** [U].

**So what for Vigil.** "One shared source of truth" must be vigild's state, not a prose file: the task graph with `blocked_by` edges, declared write scopes held as leases, the packet revision each PR saw, and rulings on `main`. Coherence is enforced at four moments:

1. **Plan:** invariants go into the spec and the reviewer's checklist.
2. **Dispatch:** an overlapping scope is refused, including against open foreign PRs.
3. **Land:** vigild rebases in the vault and re-verifies on the live `main` head (build-list item 10). This is what AgenticFlict's 27.67% calls for.
4. **After:** stale-PR caps and a backlog-age metric.

Treat `AGENTS.md`/`CLAUDE.md` as a map rendered per harness and versioned in the packet, with a static drift check of the AgentBrief kind ([AgentBrief](https://github.com/seanmcmahon101/AgentBrief)). Do not expect it to produce coherence.

### 4.2 Every tool converges on project → task → run → attempt, and none enforces WIP

The data models are now readable from source and API docs and they agree:

- **T3 Code:** environment → project → thread → run → attempt → execution node. `RunAttempt.reason` ∈ {initial, steering_restart, retry, provider_recovery}. Node kinds include `approval_request` and `user_input_request`, and a pending request carries a `blocking` bit [V] ([orchestrationV2.ts](https://github.com/pingdotgg/t3code/blob/main/packages/contracts/src/orchestrationV2.ts)).
- **Vibe Kanban:** Project → Task → Workspace (attempt) → Session → ExecutionProcess → Turn. The PR hangs off the workspace, not the task [V] ([models](https://github.com/BloopAI/vibe-kanban/tree/main/crates/db/src/models)).
- **Warp:** Factory → Work item → Run, with a foreman as the only agent that talks to you [V] ([Warp](https://docs.warp.dev/factories/)).
- **Devin:** sessions with `status_detail` ∈ {working, waiting_for_user, waiting_for_approval, finished}, plus `max_acu_limit` [V] ([Devin API](https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions)).
- **Cursor:** agent → runs, `409 agent_busy` unless the follow-up is sent with `delivery: steer` [V] ([Cursor API](https://cursor.com/docs/cloud-agent/api/endpoints)).

Three regularities follow [I]. The PR is a link on the attempt, never the parent object. Lineage (`delegatedFrom`, session trees, coordinator → threads) is a standard field. "Needs a human" is a status detail on the run, not a separate object.

What collapses at scale is the human, not the schema. No surveyed tool ships a cross-project priority queue or a hard WIP limit. Claude Projects says outright that a thread limit "isn't a hard cap"; the enforced limit is 200 new threads a day [V]. Queues exist only per thread (T3 `queuePosition`, Claude's queued messages). The anti-clutter mechanisms with evidence are settle/auto-settle and archive (T3; Claude's "Resolved" after a week of inactivity), done-states that stay sticky until acted on (the herdr plugin, which fixes a core behaviour where a finished agent "drops out of the queue before you have dealt with it" [R] ([herdr-attention-queue](https://github.com/justmytwospence/herdr-attention-queue))), and bounded repo sets (Graphite's 3 or 30) [V]. Cross-project views are global first: Warp's Runs and Inbox are team-wide, GitHub's agents panel spans repos, and Claude's Overview groups threads by state, not by repo [V]. Two budgets on one run have no precedent. T3 keeps subscription windows and priced cost in two separate contracts [V] ([usage.ts](https://github.com/pingdotgg/t3code/blob/main/packages/contracts/src/usage.ts)).

**So what for Vigil.** Vigil's `job → task → session → PR` maps onto this shape. Add `attempt.reason` and `limitRecovery {resetAt, autoResume, snooze}` verbatim. They separate a subscription-window stall from an API-dollar refusal, which no other tool needs to do. Enforce what nobody else enforces: a WIP cap per repo and a cap on in-flight PRs per repo in `configs/`, both refusals. Make the project a facet on one global list, not a navigation level. The founder has two to three projects, and the home must answer "what needs me" across all of them.

### 4.3 The measured UX failure is approval spam, not clutter

Status vocabularies converge on five or six human-meaningful buckets. Claude Projects' are the cleanest: Ready for review, Waiting on you ("need your reply or approval, or that failed"), Working, Landing, Idle, Resolved [V]. Devin added two refinements that matter for a phone-first owner: the sidebar "names the specific approval a session waits on", and status "stops asking you to review… once that step is done". It also backs off repeated failure notifications [V] ([Devin release notes](https://docs.devin.ai/release-notes/overview)). Linear's Inbox defaults to a Priority tab and runs on J/K/U/H [V] ([Linear Inbox](https://linear.app/docs/inbox)). Graphite treats PRs like email, with a "Returned to you" section [V].

The anti-pattern with the hardest evidence is volume. One Codex response needed 25 approvals, read-only commands prompted "dozens of times", and users called Full Access "all or nothing" [V] ([openai/codex#10187](https://github.com/openai/codex/issues/10187)). Others report a human ceiling of "three to four threads" [R] ([Osmani](https://addyosmani.com/blog/cognitive-parallel-agents/)), a user who stopped running parallel agents once the easy backlog ran out [R, snippet], and four times the tokens and bugs with four Conductor agents [R] ([madewithlove](https://madewithlove.com/blog/conductor-running-multiple-ai-coding-agents-in-parallel/)). Every approval card surveyed is binary (approve/deny, with a "rest of thread" scope). The richest is Devin's clickable-choice structured questions [V]. **Nobody ships a card with a highlighted recommendation and a free-text override**, and nobody turns a card answer into a reviewed rule [V, absence]. Screenshots could not be viewed in this environment; every layout claim here comes from docs, source or changelogs.

**So what for Vigil.** Design the card budget as a metric before designing the cards. The verifier, the container and the gateway already gate routine actions, so the human sees only exceptions (6.3). Adopt Claude's buckets mapped to the FSM, Devin's named blocker and auto-clear, herdr's sticky FIFO ordering, and Linear's keys. The recommendation + override + "make it a rule" card is the one UX element with no precedent and a perfect fit for the founder (A2).

### 4.4 Labs absorb the loop; nobody is building the gate

In the six months to October 2026 every lab shipped the outer surface:

- **Anthropic:** routines on cron and GitHub webhooks [V] ([routines](https://claude.com/blog/introducing-routines-in-claude-code)); Code Review tiers, org-wide review, `pipeline()`/`parallel()` workflows and self-hosted runners [V] ([changelog](https://code.claude.com/docs/en/changelog)).
- **OpenAI:** reusable cloud environments and automatic cloud reviews [R] ([The Decoder](https://the-decoder.com/openai-expands-codex-and-its-api-at-devday-with-security-scans-a-decisions-api-and-ultrafast/)).
- **GitHub:** Copilot projects, automations that "propose improvements for you to review", Agent Merge and Copilot included in Enterprise [V].
- **Cursor:** Projects and the Agent SDK [V].

Self-hosting from the labs is execution only; the loop and inference stay hosted [R] ([The New Stack](https://thenewstack.io/anthropic-mcp-tunnels-sandboxes/)). Subscriptions are being shaped against unattended factory use. Routines have daily caps, OpenAI cut the $200 Pro Codex allowance from 20× to 10× Plus [R] ([Engadget](https://www.engadget.com/2272106/openai-adds-dollar500-pro-subscription-nerfs-its-existing-dollar200-tier/)), and Gemini CLI dropped individuals. Consolidation hit the harness layer too: SpaceX (merged with xAI) bought Cursor for a reported $60B [R] ([SiliconANGLE](https://siliconangle.com/2026/06-16/spacex-acquire-vibe-coding-startup-cursor-60b/)), and Cursor's Plus tier now bundles Grok Build [V] ([Cursor pricing](https://cursor.com/pricing)). Standards are settling at the tool and host layers: MCP (≈47k registry servers [R]), SKILL.md in 9 of 11 harnesses, ACP in 6 of 11 as the "harness hosting" role [V] ([arXiv 2609.00006](https://arxiv.org/abs/2609.00006)). OTel GenAI conventions are all still "Development" [R].

Not found first-party anywhere: hidden tests in a fresh checkout, a verifier outside the worker's reach, an autonomy ladder per change class, or per-task refuse-not-warn stops. 23% of enterprises have no real-time way to stop an agent's spend, and 28% built their own gateways [R, n=166] ([VentureBeat](https://venturebeat.com/resources/agentic-orchestration-model-makers-are-selling-their-own-ai-agent-platforms-but-only-2-of-enterprises-say-the-model-was-the-main-reason-they-chose-one)). Security points the same way. In Comment and Control, three vendors' GitHub-triggered agents leaked API keys and tokens through their own PR comments, and no CVEs were issued [V] ([CSA](https://labs.cloudsecurityalliance.org/research/csa-research-note-comment-control-github-prompt-injection-20/)).

The disconfirming evidence, reported fairly. Agent-PR merge rates are rising (Octoverse). Robert C. Martin no longer reads his agents' code [R] ([explainx](https://www.explainx.ai/blog/uncle-bob-ai-coding-gauntlet-tests-not-reviews-july-2026)), but he relies on agent-written acceptance tests and mechanical constraints, which is still a gate. Meta lands about two-thirds of changes without significant human edits, behind deterministic gates [V] ([Meta](https://engineering.fb.com/2026/10/19/ml-applications/thin-orchestrator-ai-agent-architecture/)). The absorption thesis says what survives is durable execution, portfolio routing and in-tenant deployment [V, opinion] ([Jankowski](https://thomasjankowski.com/writing/agent-layer-skipped-orchestration/)).

**So what for Vigil.** Spend nothing on features that increase session volume (cloud sessions, triggers, coordinator chat, babysitting). The labs ship those for free. Spend on what their incentives keep them from building, because it lowers merge rate or spend: the verifier, the ladder, the hard stops, no-secret workers, provenance, and a portfolio that includes the local model. Bind integrations to protocols (headless `-p`/`exec`, JSON-RPC/ACP, base-URL override), not to product names.

---

## 5. Vigil core design implications

### 5.1 Data model

These are additions to the existing `job → task → session → PR` FSM. Every row carries `provenance`, and every state change writes an `events` row (CLAUDE.md).

| Entity | Key fields | Precedent | Why |
|---|---|---|---|
| `project` | repo set (from `repos.yaml`), allowed backends, WIP cap, in-flight PR cap, hotspot globs | Warp "group repos that ship together" [V]; Graphite bounded set [V] | The facet on the global list; policy owner |
| `factory_config` | harness + pinned version/digest, model backend, prompt template rev, policy profile, budget class, allowed shapes, rung | Warp `agents/*.md` [V]; prior report's (model, harness, prompt) triple | The thing scoreboards and routing compare; versioned in `configs/factories/` |
| `brief` | author session (advisor), text, cited rulings, proposed jobs, status {proposed, approved, delivered, superseded}, `approved_by: human` | Claude "Suggested threads" with start-all [V] | Replaces the hand relay; only the owner moves it to approved |
| `job` / `task` | existing contract fields + `blocked_by[]`, `scope_globs[]`, `brief_id`, `origin {vigil, foreign}` | Kiro waves [V]; design.md disjointness rule | The graph is data, not prose |
| `scope_lease` | task_id, globs, acquired/released, conflicts_with | Propel "scope contracts" [V, vendor]; CooperBench file claiming [V] | Dispatch-time refusal on overlap |
| `attempt` | `reason {initial, retry, steering_restart, provider_recovery, rebase_on_land}`, `limit_recovery {reset_at, auto_resume, snooze}` | T3 `RunAttempt`, `limitRecovery` [V] | Separates subscription stalls from dollar refusals |
| `verdict` | gate tier, base/before/after JUnit diff, hidden-test categories, rebased-head SHA, `stale` flag | Vigil verifier (built) | The primary fact on every PR row |
| `decision_card` | kind {spec, brief, merge-ready, question, page, breaker}, options[], recommended option + rationale, override text, scope {this run, this task, this factory, standing rule}, `blocking`, answered_via {web, phone, mcp}, auto-clear condition | T3 `approval_request` + `blocking` [V]; Devin named blockers [V]; Claude "broader option" [V] | The single decision surface |
| `ruling` | id, text, source card, machine-checkable? (config key), draft PR, status {draft, merged, retired} | Claude "remember the correction" [V]; Warp policy-in-instructions [V] | "From now on" becomes a reviewed artifact; coord cites only merged rulings |
| `budget_ledger` | per run: API $ (gateway, cost of record), subscription window {account, kind, used_pct, resets_at, source: probe/manual, stale_at}; rollups task/day/month | T3 `ServerProviderUsageWindow` + `UsageCostSource` [V] | Two budgets on one row (no precedent) |
| thread UI state | `settled_at`, `snoozed_until`, `pinned_at`, each with its reverse | T3: "A one-way door is a bug" [V] ([AGENTS.md](https://github.com/pingdotgg/t3code/blob/main/AGENTS.md)) | Keeps the home quiet without hiding anything |

### 5.2 The coherence layer: one source of truth, enforced at four moments

The source of truth is `vigil.db` + the vault + `configs/` and `docs/owner-rulings.md` on `main`. Harness-side files are renderings of it, never the authority.

1. **Plan.** The spec carries an `## Interfaces` section (already required for parallel writers) and a product-invariants list. Invariants go into the reviewer's checklist as rules with include globs. The reviewer may block only on checkable invariants, and its precision is recorded against the owner's merge decisions (no vendor publishes this number).
2. **Dispatch.** vigild acquires scope leases. A task whose globs overlap an active lease, an open job PR's touched files, or an open foreign PR's touched files is held with a `blocked_by` edge, not run (CooperBench). Hotspot files (CSS bundles, barrels, changelogs, migrations, lockfiles) are serial per repo (Organ, CooperBench). Dependent work becomes a chain of at most three links (build-list item 15).
3. **Run.** The packet records the `CLAUDE.md`/`AGENTS.md`/codemap revision and the ruling IDs it carried. Policy is rendered from `configs/` per harness (managed-settings.json, `requirements.toml`, OpenCode policies, Grok `config.toml`). A canary test asserts each rendered file denies the same commands. The container and smokescreen remain the only boundary that counts.
4. **Land.** vigild rebases in the vault, re-runs the verifier on the rebased head, and marks the verdict stale if `main` moved, as Conductor and Kilo do at the view layer [V]. Zero-diff and out-of-scope bundles fail mechanically. A branch older than 24 h, and the share of PRs that conflict at land, are weekly-report columns. A vault-side check flags new symbols added by two open jobs (the cross-PR duplicate check nobody ships).

### 5.3 Project and queue model

There is one global dispatch queue ordered by (inbox-approved time, priority label, chain position), gated in sequence by budget, then WIP per repo, then scope leases. **Serial by default within a repo**; parallel only across disjoint leases. Factory Missions makes the same choice for the same reason ("reduces conflicts and inconsistent architectural decisions" [R]). Per-repo WIP and in-flight PR caps are refusals, not preferences. When a cap trips, the card says which cap and what would free it. The project is a filter on every view and the default grouping on the Jobs page, never the home's primary axis.

### 5.4 Cross-harness abstraction

One executor contract (an ACP-shaped session: packet in, streamed updates, `vigil_result` out; gateway token on stdin; cost from the gateway; same image; no egress), with a version-pinned adapter and recorded transcripts per harness (build-list item 12a). The test for admission is mechanical: **can it run with no vendor credential, pointed at the gateway, inside the egress-locked container?** If it cannot, it is an *external factory*, and Vigil verifies its PRs instead of hosting it.

| Harness | Invocation | Gateway path | Own sandbox/policy | Role in Vigil | When |
|---|---|---|---|---|---|
| Claude Code 2.1.306 (pinned) | `claude -p`, stream-json; never `--bare` | `ANTHROPIC_BASE_URL` + token [V, prior] | managed-settings; hooks `onFailure: block` | Current worker, reviewer, auditor | Now |
| OpenCode | `opencode run --format json`; `serve`/`--attach` | `OPENCODE_CONFIG_CONTENT` [V, prior] | None; container only [V] | First added worker; local-model host | Phase 2 |
| Codex CLI | `codex exec --json` or app-server over stdio [R] | `model_providers.base_url`; Responses API only [V, prior] | `external-sandbox` | Second added worker | Phase 2 |
| Grok Build | `grok -p -m <key> --output-format plain --sandbox off` [R] | Per-model `base_url` + `env_key` [R] | Sandbox off by default; loads Claude/Cursor hooks by default, ignoring `permissionDecision` [R] | Worker *if* Q4 passes; disable foreign hook loading | Spike Phase 0, adapter Phase 2 |
| Factory Droid | `droid exec`, JSON/stream-jsonrpc, fails fast on permission violations [R] | BYOK `customModels.baseUrl` [R] | Autonomy levels; air-gap is Enterprise-only [R] | Worker *if* Q5 passes | Spike Phase 0 |
| Cursor (`agent`, cloud, Projects) | `agent -p` needs `CURSOR_API_KEY` [V, prior] | None evidenced | — | External factory: intake its PRs | Phase 2 intake |
| Claude Projects / Copilot / Codex cloud | Vendor cloud | — | Vendor | External factories: intake their PRs on repos whose policy allows hosted backends | Phase 2 intake |
| Local Qwen3.6-35B-A3B | Behind the gateway via OpenCode or Claude Code | llama-server on the tower | — | Grounded reviewer, then best-of-n generator; not a solo worker (prior report) | Phase 3 (needs phase 5) |

Foreign-PR intake is the one new idea in this table, so it needs care [I]. A foreign PR has no Vigil contract. The verifier can still run base/before/after on the repo's suite in a fresh vault checkout, and hidden tests if the owner attaches a contract after the fact. The reviewer packet is the same. The private-repo rule still binds: on a repo where `repos.yaml` lists no hosted backend, a foreign PR from a hosted factory is itself a page.

---

## 6. Command-center UX spec (desktop/web first)

### 6.1 Information hierarchy

Four levels, top to bottom, on every page:

1. **Header strip (one line):** API $ today / pacing line / month, the subscription window with `resets_at` (or `unavailable`), breakers tripped, queue depth, WIP per repo, verifier queue wait. Numbers only, with "estimate, not invoice" in the tooltip (Warp [V]).
2. **Needs you:** typed cards, sticky, FIFO within kind, ordered page > breaker > brief/spec > ready-to-merge > question (refines the build list's UI brief).
3. **In flight:** jobs grouped by state, one line each.
4. **Settled:** counts only ("41 done this week"), expandable (T3 `olderSettled` [V]).

### 6.2 Primary views

These map onto `docs/ui.md`'s nine pages, which keeps the page count.

| View | Replaces | Content | Primary actions |
|---|---|---|---|
| `/` Inbox | `/` Board | Levels 1–4 above, all projects | Answer card (1/2/3, `o` override, `r` make rule), settle, snooze |
| `/jobs` | Board table | The existing table, grouped by state; facets project, factory, origin | Filter, open |
| `/job/:id` | same | Tree (brief → coord → workers → reviewer → auditor), timeline, verdict, PR rail with diff and line comments routed to the run | Kill, retry with reason, open on GitHub |
| `/review` | same | Ready-to-merge queue: verdict first, then findings by severity, then diff stat; foreign PRs labelled | Open on GitHub to merge |
| `/factories` | `/decider` + part of `/new` | Factory configs, scoreboard Pareto per (model, harness, prompt), rung per shape, decider stats | Propose config change (draft PR) |
| `/budget` | same | Two meters, per-task cost per triple, most-expensive list | — (caps change only by PR) |
| `/rulings` | new (takes `/new`'s slot; `/new` folds into a palette command) | Every ruling with its source card, status, draft PR, last cited | Retire (draft PR) |
| `/talk` | same | Advisor and coord threads, with brief cards inline | Propose brief (advisor), approve (owner, in Inbox only) |
| `/watch` | same | Unchanged | — |

### 6.3 Attention and triage model

A **decision card** has six parts. Each must be readable on a phone without opening anything else (Devin: name the exact action [V]):

1. A one-line question that names the blocker ("Spec pa-0151 touches `billing/` (rule 2): approve at Opus, rung 0?").
2. Two to four options, with the recommended one marked and a one-line rationale. The recommendation comes from coord or the decider and carries its confidence.
3. A free-text override.
4. A scope selector: this run / this task / this factory / standing rule. A standing rule opens a draft PR to `docs/owner-rulings.md`, plus the config key if the rule is machine-checkable. A human merges it, and coord cites only merged rulings.
5. Evidence links: verdict, diff stat, cost so far.
6. An auto-clear condition: the card disappears when the step is done elsewhere (Devin [V]).

Cards have a `blocking` bit. A non-blocking question lets the run continue (T3 [V]). Similar cards from one brief batch ("approve 3 specs from brief b-12": approve all / review each).

The card budget is ≤10 per day. Breaching it is itself a weekly finding: which kind of card, and which ruling would have prevented it. Notifications: push only for pages, breakers and blocking cards older than 30 min. Repeated failures back off (Devin [V]). Never notify on a finished turn.

### 6.4 Navigation

Keyboard first, following Linear and T3:

- `g i` / `g j` / `g r` / `g f` / `g b` / `g u` jump to Inbox / Jobs / Review / Factories / Budget / rulings.
- `j`/`k` move, `Enter` opens, `Esc` goes back.
- `1`–`4` answer a card, `o` overrides, `r` makes a rule, `s` settles, `h` snoozes, `u` undoes (every state has a reverse).
- `/` filters. `⌘K` opens a palette over jobs, PRs, rulings, factories and commands; it includes settled and archived items (Devin [V]) and rejects ambiguous IDs across projects (Kilo [V]).
- Hover or focus shows a preview card (title, state, named blocker, last line, PR, cost) instead of opening a pane.

### 6.5 Density rules

- **One line per job row**, at most seven visible columns: id, project, state glyph + word, named blocker or next step, verdict, $ / window, age. Everything else is in the hover card or the detail page.
- **State is a word plus a glyph** (working / blocked / done), never colour, keeping `ui.md`'s no-red/green rule. The FSM state shows on hover.
- **"Done" means the verifier's verdict**, never an agent's report (build-list UI brief).
- **Numbers are right-aligned and tabular.** Money appears only as gateway-metered cost; no CLI self-reported cost.
- **Side rails are collapsed by default.** Diffs live in a rail on `/job/:id`. The PR itself stays on GitHub.
- Keep `ui.md`'s budgets: no modals, no horizontal scroll at 1280 px, <100 KB per page, one SSE stream, no polling.

### 6.6 Never do this

1. Per-command approval prompts as a safety mechanism. The container, gateway and verifier are the boundary; per-action approvals produced Codex's 25-prompt response.
2. A kanban board or a grid of live agent terminals as the home. Columns do not scale past about 20 runs, and a grid assumes the owner watches agents (A3).
3. A done state that clears when viewed, or rows that reorder when clicked (herdr).
4. Showing a worker's self-reported test result, "tests passed" text, or `total_cost_usd` anywhere a verdict or a cost belongs.
5. A merge, auto-merge or "approve all PRs" button that acts with vigild's credentials. The human merges on GitHub until a shape earns auto-land.
6. A notification per turn, per thread start, or per retry.
7. One-way doors: settle without unsettle, snooze without wake, a rule without retire.
8. A secret field, a login flow for a provider, or "paste your API key" anywhere in the UI.
9. Colour-coded status, gradients, cards with shadows, or animation other than the 600 ms live-row pulse.
10. Project-first navigation that hides another project's blocked card.
11. Making a decision on `/talk`. Talk proposes; only the Inbox decides (design.md).

---

## 7. Differentiation and defensibility

| Capability | First-party status (Oct 2026) | Vigil | Defensible at 18 months? |
|---|---|---|---|
| Cloud/background sessions, coordinator + workers, triggers | Shipped by Anthropic, Cursor, GitHub, OpenAI [V] | Has (vigild, coord, MCP) | **No.** Parity is the floor; do not compete |
| PR babysitting, CI-fix, conflict-fix, auto-merge | Shipped (Agent Merge, auto-fix, `/babysit`) [V/R] | Rebase-on-land with re-verification | Partly: the re-verification is what is distinctive |
| Tiered LLM review | Shipped, cheap [V] | Fresh-context Sonnet + Opus audit | No as a feature; yes as "review with verifier evidence, precision measured" |
| Verifier outside the worker's reach, hidden tests, single-commit checkout | Not found [V, absence]; Factory Missions' validators are blind but in-run [R] | Built | **Yes.** It lowers merge rate, which runs against vendor incentives [I] |
| Earned autonomy per change class (SPRT ladder) | Not found; GitHub automations propose for approval [V] | Designed, rung 0 | Yes, once planted-defect data exists |
| Per-task refuse-not-warn $ stop at the only key holder | Not found; monthly/org caps and warnings [V] | Built (gateway) | Yes, and buyers want it (23%/28%) [R] |
| No-secret, no-egress workers; host-only GitHub | Vendors leaked keys through their own comments [V] | Built | Yes |
| Provenance-tagged traces → local training | Sequoia's recipe [V]; Octoverse admits its detection is a "floor" [V] | Built (tags), training blocked | Yes, but its value is unproven (local model weak) |
| Cross-vendor portfolio including a local model | Labs keep inference hosted [R] | Partial | Yes in principle; small in practice today |
| Recommendation + override card → reviewed ruling | Not found [V, absence]; nearest is Claude "remember the correction" [V] | Proposed | **Weak moat, high fit.** Easy to copy; worth building because it fits the founder, not because it protects |
| Command-center UI | T3 (free), Conductor, Claude/Cursor Projects, Copilot app [V] | Phase 3 | **No** |

**What the labs will absorb within 12 months** [I, from shipped evidence]: everything in the first three rows, plus mobile remote control (Cursor iOS, Conductor 0.92, T3), multi-repo projects, ACP hosting, usage dashboards and monthly caps, security scanning of agent output, and model routing within one vendor (Copilot Fusion, Factory Router). GitHub is the nearest threat. Copilot projects + automations + Agent Merge + Enterprise bundling is a cloud factory with a human approval step, and its merge gate is still the repo's own CI [I].

**Where the thesis is weak, stated plainly.**

1. **"One place to manage every factory" is not a moat and partly not reachable.** The surface is free and fast-moving elsewhere. Most of the founder's tools cannot run keyless inside Vigil's boundary: Cursor needs a vendor key, Antigravity a login, and Amp is vendor-metered (prior report). Grok Build and Droid are unproven. "Every factory" honestly means "every factory's PRs", through intake.
2. **"Many factory configs in parallel on one project" runs against the evidence.** CooperBench, AgenticFlict, Organ and Factory's own serial-by-default choice all say that parallel writers on shared code cost more than they return. The value of several configs is comparison (the scoreboard) and routing by shape, not concurrency on one repo.
3. **"Coherence through a shared source of truth" is right only if the truth is state, not prose.** Shared context files have no measured coherence effect.
4. **Subscription harnesses do not fit the money rule.** The founder's two-budget reality (subscription for advisor and coord, API for factories) is correct. Factory-scale subscription use is being capped by the vendors and cannot pass through the metering gateway, so any "run Grok Build on my SuperGrok plan inside Vigil" plan conflicts with "every hosted call goes through the gateway".
5. **The local model is not yet a worker.** No evidence shows a ≤35B model winning an own-repo shape under hidden tests (prior report). Its defensible roles wait on phase 5.
6. **There is no external validation.** This is a market of one owner. Demand evidence for self-hosted control planes is enterprise and regulated (Coder Agents, the VB survey), not indie. That is fine for a personal factory, but it means "defensible" should be read as "not wasted when the labs ship the next thing", not as a business moat.

---

## 8. Sequenced roadmap

Vigil's internal phase numbers differ from these. Phase 0–3 below are this report's sequencing of Vigil phase 3 (UI) and what it depends on. Build-list item numbers refer to `coord-prompt-post-phase-2.md`.

| Phase | Scope | Build-list items that slot here | Success criteria | Deliberately not built |
|---|---|---|---|---|
| **0: Data before pixels** (Nov 2026, ~3 wks) | ADR + migrations for `brief`, `decision_card`, `ruling`, `budget_ledger`, `scope_lease`, attempt `reason`/`limit_recovery`; brief flow on MCP; dispatch-time lease refusal; card-budget instrumentation; Grok/Droid spikes; envelope fix (Q1) | 1 (docs, envelope), 2 (abort), 4 (reviewer evidence), 6 (base cache, flakes), 10 (rebase-on-land), 11 (`wait_for`, MCP surface test), 12a (replay transcripts) | One brief goes advisor → owner (phone) → coord → report with no hand-copied text; relay time is measured before and after; a planted overlapping task is refused; verdicts carry the rebased SHA | Any UI page; new harness adapters; foreign intake |
| **1: Inbox-first cockpit** (Dec 2026) | `/` Inbox, `/jobs`, `/job/:id`, `/review`, `/budget` (two meters), `/rulings`; palette; keys; notifications; ui.md revision; "make it a rule" → draft PR | 7 (scoreboard v0 feeds `/factories` stub), 9 (`review.yaml`, `automations.yaml`), 3 (single-commit everywhere) | A full week of owner decisions made only from the Inbox (web + phone browser); ≤10 cards/day; median answer time falls; zero merged PRs without a verifier verdict on screen; each page <100 KB | Live agent grids; in-UI merge; drag-and-drop boards; project-first nav; theming |
| **2: Many factories, one gate** (Q1 2027) | `factory_config` as code; executor contract with OpenCode then Codex (Grok/Droid if their spikes pass); per-harness policy rendering + canary tests; foreign-PR intake (pilot on `vigil`); `/factories` Pareto; cross-PR duplicate-symbol check; hotspot serialisation | 13 (ask-gate), 14 (codemap), 15 (chains), 16 (flag skills), 19 (security findings), 20 (second seat), 8 (retry packet), 12 (local pricing) | Same task shape runs on ≥2 harnesses with comparable scoreboard rows; conflict-at-land rate and open-PR age reported weekly and flat or falling as volume rises; a foreign PR gets a verdict before the owner merges it | Hosting subscription-login harnesses; Cursor/Gemini/Amp adapters; a global priority-scoring model |
| **3: Earned autonomy and the tower** (after phase 5 serves jobs) | Planted-defect catalog; SPRT ladder live; local grounded reviewer at rung 1; best-of-n on tower; auto-land for docs/lint/deps-patch only; replay eval | 5 (hidden-test admission, hackability), 17 (self-edit job), 18 (test selection), 20a (test-signal reviewer), 21–23 (Phase C), deferred V5, local best-of-n, fine-tune E9 | First shape promoted by the SPRT with audits clean; ≥1 class auto-lands with a 10% audit and no revert in 48 h; owner PR reviews per week fall while the defect escape rate does not rise | Auto-land on money/auth/migration/config paths; any LLM judge in reward or gating; a fine-tune before ≥300 qualifying traces |

Not slotted on purpose: the warm pool, the run-and-observe image (E7) and the console (E10) stay in Track D after Phase 2. T3 Code stays *alongside*, as the owner's interactive cockpit calling `vigil mcp`, as the build list already says.

### Mobile, later

Mobile is the Inbox's "Needs you" level and nothing else. T3's own framing is "suited to attention, not deep review" [R] ([Flavio Copes](https://flaviocopes.com/t3-code/)). Ship it first as the same Inbox page served responsively over Tailscale: card answers, override text, "make it a rule", and push for pages and breakers. A native app is justified only if phone answers exceed half of all card answers and browser push proves unreliable. Never put diff review, merge, budget edits or secrets on the phone.

---

## 9. Risk register

| Risk | Likelihood | Impact | Mitigation | Leading indicator |
|---|---|---|---|---|
| A lab or GitHub ships independent hidden-test verification | Medium | High (erases headline differentiator) | Keep the verifier harness-neutral so it can gate *their* PRs (foreign intake); compete on ladder + hard stops + provenance | Changelog terms "hidden tests", "held-out", "verifier", "validation contract" at Anthropic/GitHub/Cursor; Factory Missions moving validators out of process |
| Approval spam recreated for one person | High without the metric | High (owner abandons the UI) | Card budget ≤10/day; batch by brief; promote repeated answers to rulings; non-blocking cards | Cards/day; share of cards with the same answer three times running |
| UI scope creep against T3-scale competitors | High | Medium | Nine pages, ui.md budgets, never-do list; T3 stays alongside | Pages or components added outside the spec; weeks spent on UI vs trust path |
| Harness churn (Grok Build/Cursor consolidation, CLI withdrawals, version supply chain) | High | Medium | Protocol-bound adapters; recorded transcripts; pin by version and digest; a malicious-version notice for Claude Code 2.1.312–313 in Cursor's marketplace shows why [V, title] ([Cursor blog](https://cursor.com/blog/page/5)) | Vendor deprecation notices; adapter replay failures on bump |
| Verifier saturates the Mac mini | High as volume rises | High (queue stalls) | Base-run cache, flake quarantine, selection (items 6, 18); verifier queue wait in the header | Verifier queue wait p90; runs per attempt |
| Subscription meter unreadable | Medium | Low–medium | Probe with an explicit `unavailable` state; manual entry with staleness | Probe failure rate; meter age |
| Scope leases too coarse, so serial throughput starves | Medium | Medium | Glob-level leases, chain small; measure held-time | Mean lease wait; share of tasks held >1 h |
| Foreign intake breaches the private-repo rule | Low–medium | High | Intake gated by `repos.yaml` backend list; hosted-origin PR on a private repo = page | Any foreign PR on a repo with no hosted backend |
| Spend through the gateway exceeds the envelope with more factories | Medium | Medium | Hard caps already refuse; per-factory budget class; pacing line on the strip | Days at >80% of pacing; refusals per day |
| Rulings drift or contradict | Medium | Medium | Ruling IDs cited per packet; retire via PR; a weekly "rulings cited 0 times" list | Contradictory card answers; uncited rulings |
| Owner remains the throughput limit (every PR crosses him) | Certain until auto-land | High | Phase 3 ladder; planted-defect catalog scheduled now | Owner PR reviews/week; median time in "ready" |

---

## 10. Source list

Dates are publication or last-updated dates where known; otherwise the date the note read the source (30 Oct 2026, written "read 30 Oct"). The grade applies to how the source was used.

| Source | Date | Grade |
|---|---|---|
| [Claude Code: Projects](https://code.claude.com/docs/en/claude-projects.md) | read 30 Oct 2026 | V |
| [Claude Code in the cloud](https://code.claude.com/docs/en/claude-code-on-the-web) | read 30 Oct 2026 | V |
| [Claude Code changelog](https://code.claude.com/docs/en/changelog) | 14–26 Oct 2026 | V |
| [Introducing routines](https://claude.com/blog/introducing-routines-in-claude-code) | 14 Apr 2026 | V |
| [Claude Tag](https://www.anthropic.com/news/introducing-claude-tag) | 23 Jun 2026 | V |
| [Cursor: Introducing Projects](https://cursor.com/blog/projects) | 10 Sep 2026 | V |
| [Cursor changelog](https://cursor.com/en-US/changelog) | Sep–Oct 2026 | V |
| [Cursor pricing](https://cursor.com/pricing) | read 30 Oct 2026 | V |
| [Cursor Cloud Agents API](https://cursor.com/docs/cloud-agent/api/endpoints) | read 30 Oct 2026 | V |
| [Cursor blog index](https://cursor.com/blog/page/5) | titles to 29 Oct 2026 | V (titles) |
| [SiliconANGLE: SpaceX–Cursor](https://siliconangle.com/2026/06-16/spacex-acquire-vibe-coding-startup-cursor-60b/) | 16 Jun 2026 | R |
| [x.ai: Grok Build CLI](https://x.ai/news/grok-build-cli) | 25 May 2026 | V |
| [Orq.ai: Grok Build](https://docs.orq.ai/docs/integrations/code-assistants/grok-build) | undated | R |
| [Agentic Control Plane: Grok Build](https://agenticcontrolplane.com/controls/grok-build) | 2026 | R |
| [Codex app-server guide](https://codex.danielvaughan.com/2026/04/15/codex-app-server-complete-guide/) | 15 Apr, upd. 28 Oct 2026 | R |
| [Codex pricing](https://chatgpt.com/codex/pricing/) | read 30 Oct 2026 | V (stale) |
| [openai/codex#10187](https://github.com/openai/codex/issues/10187) | 2026 | V |
| [The Decoder: DevDay](https://the-decoder.com/openai-expands-codex-and-its-api-at-devday-with-security-scans-a-decisions-api-and-ultrafast/) | 29 Sep 2026 | R |
| [Engadget: Pro tiers](https://www.engadget.com/2272106/openai-adds-dollar500-pro-subscription-nerfs-its-existing-dollar200-tier/) | Sep 2026 | R |
| [GitHub: Copilot cloud agent troubleshooting](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/troubleshoot-cloud-agent) | read 30 Oct 2026 | V |
| [GitHub Universe 2026](https://github.blog/news-insights/company-news/github-universe-2026-evolving-every-layer-of-the-stack/) | 28 Oct 2026 | V |
| [Agent Merge](https://github.blog/changelog/2026-10-28-agent-merge-watches-and-fixes-pull-requests-in-the-cloud/) | 28 Oct 2026 | V |
| [Octoverse 2026](https://github.blog/news-insights/octoverse/octoverse-commits-pushes-reach-new-highs-in-2026-as-developers-build-with-agents/) | 28 Oct 2026 | V |
| [Antigravity 2.0](https://www.antigravity.google/blog/introducing-google-antigravity-2) | 19 May 2026 | V |
| [gemini-cli #27274](https://github.com/google-gemini/gemini-cli/discussions/27274) | May–Jun 2026 | V |
| [Devin Desktop FAQ](https://docs.devin.ai/de/desktop/devin-desktop-faq) | 2 Jun 2026 | V |
| [Devin deployment](https://docs.devin.ai/enterprise/deployment/overview.md) | read 30 Oct 2026 | V |
| [Devin API v3](https://docs.devin.ai/api-reference/v3/sessions/post-organizations-sessions) | read 30 Oct 2026 | V |
| [Devin release notes](https://docs.devin.ai/release-notes/overview) | Sep–Oct 2026 | V |
| [eesel: Devin pricing](https://www.eesel.ai/blog/devin-fusion-pricing) | 2026 | R |
| [ZenML: Factory Missions](https://zenml.io/llmops-database/multi-agent-software-development-system-with-extended-autonomous-execution) | 2026 | R |
| [Latent Space wiki: Factory](https://latent.space/wiki/factory-ai-198fea7c/) | to Sep 2026 | R |
| [innfactory: Droid](https://innfactory.ai/en/ai-harness/droid/) | 20 Sep 2026 | R |
| [Factory BYOK](https://docs.factory.ai/cli/byok/) | read 30 Oct 2026 | R |
| [Amp: Self-hosted orbs](https://ampcode.com/news/self-hosted-orbs) | 22 Oct 2026 | V |
| [Warp Factories docs](https://docs.warp.dev/factories/) · [dashboard](https://docs.warp.dev/factories/factory-dashboard/) · [as-code](https://docs.warp.dev/factories/factory-as-code/) | upd. 26 Oct 2026 | V |
| [Warp pricing](https://warp.dev/pricing-c) | read 30 Oct 2026 | V |
| [OpenHands pricing](https://openhands.dev/pricing) | read 30 Oct 2026 | V |
| [T3 Code README](https://github.com/pingdotgg/t3code) · [commits](https://github.com/pingdotgg/t3code/commits/main) | 30 Oct 2026 | V |
| [T3 orchestrationV2.ts](https://github.com/pingdotgg/t3code/blob/main/packages/contracts/src/orchestrationV2.ts) · [providerUsageLimits.ts](https://github.com/pingdotgg/t3code/blob/main/packages/contracts/src/providerUsageLimits.ts) · [usage.ts](https://github.com/pingdotgg/t3code/blob/main/packages/contracts/src/usage.ts) · [AGENTS.md](https://github.com/pingdotgg/t3code/blob/main/AGENTS.md) | commit b8851fbc, 30 Oct 2026 | V |
| [Flavio Copes: T3 deep dive](https://flaviocopes.com/t3-code/) | upd. 16 Oct 2026 | R |
| [Conductor llms-full](https://www.conductor.build/llms-full.txt) · [changelog](https://www.conductor.build/changelog) | to 23 Oct 2026 | V |
| [Sculptor](https://github.com/imbue-ai/sculptor) | 28 Oct 2026 | V |
| [Vibe Kanban shutdown](https://vibekanban.com/blog/shutdown) · [models](https://github.com/BloopAI/vibe-kanban/tree/main/crates/db/src/models) | 10 Apr / 28 Oct 2026 | V |
| [Terragon OSS](https://github.com/terragon-labs/terragon-oss) · [Crystal](https://github.com/stravu/crystal) · [Roo Code](https://github.com/RooCodeInc/Roo-Code) · [Codegen](https://codegen.com/an-update-on-codegen/) | Jan–May 2026 | V |
| [Cline](https://github.com/cline/cline) · [Cline Kanban](https://www.testingcatalog.com/cline-debuts-kanban-for-local-parallel-cli-coding-agents.md) | 30 Oct / 26 Mar 2026 | V / R |
| [Kilo Agent Manager](https://kilo.ai/docs/automate/agent-manager) | read 30 Oct 2026 | V |
| [Zed Parallel Agents](https://zed.dev/docs/ai/parallel-agents.html) | read 30 Oct 2026 | V |
| [Emdash](https://github.com/generalaction/emdash) · [Paradev](https://github.com/superset-sh/superset) | Oct 2026 | V |
| [Linear agent interaction](https://linear.app/developers/agent-interaction) · [Linear Inbox](https://linear.app/docs/inbox) | read 30 Oct 2026 | V |
| [Graphite PR inbox](https://graphite.com/docs/use-pr-inbox) | read 30 Oct 2026 | V |
| [Macroscope check-run agents](https://macroscope.com/blog/introducing-check-run-agents) | 27 May 2026 | V |
| [herdr-attention-queue](https://github.com/justmytwospence/herdr-attention-queue) | 2026 | R |
| [Osmani: cognitive parallel agents](https://addyosmani.com/blog/cognitive-parallel-agents/) | 7 Apr 2026 | R (opinion) |
| [AgenticFlict, arXiv 2604.03551](https://arxiv.org/html/2604.03551v1) | 4 Apr 2026 | V |
| [CooperBench](https://cooperbench.com/blog/curse-of-coordination) | 27 Jan 2026 | V |
| [Organ merge-path post](https://dev.to/itaisagi/ai-agent-pull-requests-stuck-in-merge-conflicts-what-broke-in-our-merge-path-and-what-we-changed-4ni9) | Oct 2026 | V (self-reported) |
| [Developers Digest fan-out](https://www.developersdigest.tech/blog/parallel-agent-fanout-day) | 6 May 2026 | V |
| [Mergify State of Merge Queues](https://mergify.com/reports/state-of-merge-queues-2026) | upd. 27 Jul 2026 | V (vendor) |
| [AGENTS.md efficiency, arXiv 2601.20404](https://arxiv.org/html/2601.20404v2) | 30 Mar 2026 | V |
| [Spec Kit Agents, arXiv 2604.05278](https://arxiv.org/html/2604.05278v1) | 7 Apr 2026 | V |
| [Kiro specs](https://kiro.dev/docs/specs/best-practices/) | read 30 Oct 2026 | V |
| [Failproof AI policy files](https://befailproof.ai/ai-coding-agent-admin/managed-policy-files-for-every-coding-agent/) | 21 Oct 2026 | R |
| [OpenCode permissions](https://opencode.ai/v2/docs/permissions/) | read 30 Oct 2026 | V |
| [CSA: Comment and Control](https://labs.cloudsecurityalliance.org/research/csa-research-note-comment-control-github-prompt-injection-20/) | 17 Apr 2026 | V |
| [Review benchmark compilation](https://gitautoreview.com/blog/ai-code-review-benchmark-2026) | 14 Apr 2026 | V (compilation) / R |
| [Harness Engineering, arXiv 2609.00006](https://arxiv.org/abs/2609.00006) | Jul–Sep 2026 | V |
| [Meta: Thin Orchestrator](https://engineering.fb.com/2026/10/19/ml-applications/thin-orchestrator-ai-agent-architecture/) | 19 Oct 2026 | V |
| [VentureBeat VB Pulse](https://venturebeat.com/resources/agentic-orchestration-model-makers-are-selling-their-own-ai-agent-platforms-but-only-2-of-enterprises-say-the-model-was-the-main-reason-they-chose-one) | Oct 2026 | R (survey) |
| [The New Stack: Anthropic sandboxes](https://thenewstack.io/anthropic-mcp-tunnels-sandboxes/) | May 2026 | R |
| [Jankowski: agent layer](https://thomasjankowski.com/writing/agent-layer-skipped-orchestration/) | 15 Jun 2025 | V (opinion, >6 months old) |
| [explainx: Uncle Bob](https://www.explainx.ai/blog/uncle-bob-ai-coding-gauntlet-tests-not-reviews-july-2026) | Jul 2026 | R |
| [madewithlove: Conductor](https://madewithlove.com/blog/conductor-running-multiple-ai-coding-agents-in-parallel/) | 24 Mar 2026 | R |

Conflicts noted in the notes and how this report resolved them:

- **Grok Build launch date and 1.0 status.** The x.ai primary page (25 May, early beta) is trusted over secondary accounts.
- **Whether Claude Code reads `AGENTS.md` as a fallback.** Unresolved. The report recommends an explicit `@AGENTS.md` import or a symlink in either case.
- **Sculptor's isolation.** Its primary docs (workspace copy, containers experimental) are trusted over a roundup that says it runs in Docker.
- **CooperBench's failure split.** The authors' 63% "expectation" figure is trusted over Vaughan's 42/32/26.
- **Budget envelope.** The owner's stated envelope is trusted over the stale local checkout.

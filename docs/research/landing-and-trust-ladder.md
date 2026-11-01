# Vigil research brief: conflict-free landing, Lauren Tan's trust ladder, the one-app question, and Vigil as a service (2026-10-31)

Unverified sources per ADR-0006. Produced by an Advanced Research task; figures carry their source URL in the sources list at the end. Items the brief named that could not be verified: the seven-role "Lauren Tan's Bot Team" chart, the @0xg4tsby "60+ Grok Bots" post, x.com/0xcarnagee/status/2090102148344262659 (x.com unfetchable, no mirror), and any Bend checker-speed claim by Tan (in the talk she says she has not gone down the formal-methods path).

Vigil's conflicts at submit time are a landing-order problem, not a worker-quality problem. Have vigild own the landing: it rebases in its vault, re-verifies on the rebased SHA, and merges serially. Hand out scope leases at dispatch. Turn hot docs tables into generated, per-row files. Agent PRs conflict with their base 27.67% of the time, larger PRs conflict more, and cross-agent pairs conflict about twice as often as same-agent pairs. Most of Vigil's architecture already matches the best public practice (Tan's "trust first, then parallel"; Faros's "no merge without a gate"). The biggest gaps are a landing queue, verification evidence beyond tests, and a non-Claude advisor surface.

## TL;DR

- **Conflicts:** a vigild-owned serial landing queue that rebases, re-verifies on the rebased SHA, and squash-merges after the owner approves; path-glob scope leases at dispatch; generated docs tables from per-row files; serialised schema changes. GitHub's merge queue is an optional later layer. AgenticFlict measured a 27.67% base-conflict rate across 107K+ simulated agent PRs; conflict likelihood rises with PR size.
- **Lauren Tan / Grok Bot:** Vigil already has her core rule (the worker never grades itself; verifiers sign off). Borrow the five-layer "push corrections up the ladder" ordering as a reviewer rule, the verification-skill pattern (a fixed CLI plus an app map that produces run evidence), and pstack's one-principle-per-skill layout. Don't borrow agent self-merge or Bend proofs.
- **One app:** "Claude Duet" exists (Oct 21, 2026) as a proactive personal-agent app, not a coding orchestrator. Primary path: a remote MCP custom connector from the Claude app to a vigild MCP facade exposed through Tailscale Funnel on :443 with OAuth, plus Claude Code Remote Control for coord. Fallback: self-hosted LibreChat running an OpenRouter advisor against the same facade. Approval stays in Vigil's inbox.

## §1 PR conflicts at submit time

### 1.1 Evidence

- **AgenticFlict** (Ogenrwot & Businge, arXiv 2604.03551, May 2026): simulated merges for 107K+ of 142K+ agent PRs from 59K+ repositories; 29K+ conflicting PRs, a **27.67% conflict rate**, 336K+ conflict regions, 11.36 regions per conflicting PR on average; smaller PRs conflicted less. CONFIRMS "keep diffs small"; the owner's experience is typical.
- **Xu, Subramanian & Karthik** (arXiv 2607.04697v2, Jul 2026): 33,596 agent PRs in 2,807 repos. 40.2% of repos had co-active agent PR pairs (79.4% of agent PRs at exact overlap; 95.0% within a one-week window). Replaying 747 pairs: textual conflict rates **19.8% same-agent vs 41.7% cross-agent** (non-overlapping 95% CIs). 84.4% of conflicted files were source code; ~42% of conflicts structural (modify/delete, add/add). Lower bounds, since build and semantic conflicts follow textual ones. EXTENDS: mixing harnesses on one repo should roughly double pairwise risk unless scopes are partitioned (inferred; cross-agent pairs were only 0.5% of co-active pairs).
- **CooperBench** (Khatua et al., ICLR 2026 workshop; 600–652 tasks across Python, TypeScript, Go, Rust): GPT-5 and Claude Sonnet 4.5 agents reach ~25% with two-agent cooperation, ~50% below a solo baseline; work overlap (33.2%) the most common failure; communication reduced naive merge conflicts but not semantic incompatibility; successful pairs divided files and code ranges explicitly. CONFIRMS coordinator-decided scope leases; don't build agent-to-agent negotiation.
- **Anthropic, "Redesigning source control at Anthropic"** (Oct 13, 2026): merges from ~2,500/day in May to >30,000/day in September 2026; ~25M CI checkouts a day; a seven-person team replaced git with an in-house system (Scion) in five months. EXTENDS: server-side landing is the default at scale; Vigil's vault is the right place for it at one-Mac scale.

### 1.2 Merge queues

- **GitHub merge queue:** FIFO; each entry gets a temporary `gh-readonly-queue/main/...` branch of main plus everything ahead; `merge_group` event; every required-check workflow must list `merge_group` or the queue waits forever; a green `pull_request` run is not reused; stacked PRs GA on Oct 6, 2026 and a stack enters as one group; free.
- **Third-party:** Trunk (bisects failed batches; lanes from impacted targets), Mergify (batch 1–128), Aviator (from $20/dev/month; MIT `av` CLI), Graphite (queue on the $40 Team plan; must disable GitHub's). Vendor claims.
- **Verdict:** Vigil's problem is one human, one bot author, serial approvals. A vigild-internal queue gives the invariant (every land tested on main plus everything ahead) at zero cost without a second decision surface. GitHub's native queue later only if merges per hour grow. Don't adopt Graphite/Aviator/Trunk/Mergify at this scale.

### 1.3 Prevention techniques and risks

- **Small PRs:** an analysis of 1.5M PRs (InfoQ, GitHub stacked-PR coverage): 200–400-line PRs had 40% fewer defects and were approved 3× faster. Faros 2026: set and enforce PR size guidelines for agents. Recommend a 400-changed-line budget excluding generated files, oversize → "split?" card (threshold inferred).
- **Short-lived branches:** no primary source for agent branch-age limits; staleness rule inferred: re-rebase and re-verify before "ready" if leased paths changed on main or the branch is >24 h old.
- **Scope leases and partitioning:** CooperBench's successful pairs divided resources; OnixResearch `kiln` issues (Oct 31, 2026) propose path-based ownership with per-component evidence; Copilot offers "@copilot merge in main and resolve the conflicts" (Mar 26, 2026) and Agent Merge "watch and fix" (Oct 28, 2026), which "does not remove the need for human review"; no public documentation shows Devin, Jules, OpenHands, Factory or Cursor enforcing file-level leases across concurrent agents (absence after limited search). Vigil's planned leases go beyond anything shipped publicly.
- **Generated files for hot docs tables:** each row in `docs/features/<slug>.md`; a deterministic generator renders the table; CI fails on drift; workers never touch the table (matches foodsharing GitLab #1014's fix after union merge produced duplicates).
- **`merge=union`:** keeps both sides' lines; fixes changelog conflicts (awslabs/ferret-scan #781; pandas-ta-classic #155); risks: lines "in random order" (git docs), reworded lines kept twice (ripr-swarm #5069), safe only for append-only one-record-per-line files (KTPInfrastructure #378), GitHub's web merge historically ignored repo merge drivers (keep-a-changelog #56). Adapt: only for append-only ledgers, applied in the vault.
- **Migrations:** two tasks appending "the next step" collide or merge cleanly with duplicate numbers (add/add class). Options: one file per migration with timestamp-plus-slug and a CI check for duplicate heads, or serialise through a single schema lease (inferred).
- **AI conflict resolution accuracy is mediocre:** Shen (arXiv 2607.27674, Jul 30, 2026) on ConflictBench Java conflicts: GPT-5.4 and Gemini 3.5 Flash matched the developer's resolution on ~55% of true conflicts (Gemini 29/49 = 59.2%; OpenAI 27/49 = 55.1%) vs 36.7% for AutoMerge; the advantage "comes almost entirely from coverage"; the LLM judge accepted 4 of 5 resolutions that failed a structural check. Microsoft Gmerge (ISSTA 2022): 64.6% with GPT-3 k-shot. No published accuracy for Copilot's or Graphite's resolvers. Implication: an LLM may propose a resolution in the vault; the result must pass the full verifier on the rebased SHA; conflicts in leased logic files go back to a fresh worker.
- **Semantic merge tools** (SemanticMerge/Plastic, git-mediate): no 2026 measurements; don't adopt as a dependency.
- **Trunk-based development with flags:** standard; no agent-specific measurement; ship risky features dark, flag flip as a separate human-approved PR (inferred).

### 1.4 Rebase and re-verify on the rebased SHA

Vigil verifies the worker's branch at its base, but main moves. Copy the merge-queue invariant: test the exact tree that will land. Run the verifier on `rebase(branch, main@HEAD)`, record that SHA on the job, and allow merges only whose PR head equals the verified SHA; the SHA binding lives in vigild. CONFIRMS and EXTENDS Vigil's rule.

> **Conflict-prevention protocol for Vigil**
>
> At dispatch: each brief declares `scope` (path globs) and `shape`; vigild refuses dispatch on any overlap with an active lease (`queued_scope`, card names the holder); hot-file classes get exclusive single-holder leases (schema: `vigild/db.py`; core: `runner.py`, `assemble.py`, `fsm.py`); generated artefacts can never be leased.
>
> In the worker container (skill text): touch only files in scope, else `NEEDS_SCOPE`; keep the diff under 400 changed lines excluding generated files, else deliver the first verifiable slice and list `FOLLOW_UPS`; never edit generated tables; one migration step, never edit or renumber existing ones; no reformatting or drive-by cleanups; append-only files get new lines at the end; never merge or rebase main yourself.
>
> At landing (after reviewer + auditor pass and the owner approves): one landing mutex per repo (FIFO by approval time); in the vault fetch main, rebase (union driver only for listed append-only files), regenerate generated files, run ruff/mypy/pytest plus hidden tests on the rebased SHA; green → force-with-lease push, wait for CI on that SHA, squash-merge requiring head SHA == verified SHA; red or a conflict in a leased logic file → no auto-resolution, `REWORK` with a fresh worker and conflict context, inbox card; generated-only conflicts → regenerate and retry once; staleness sweep before any card says "ready".
>
> Don't adopt: paid hosted queues at current scale; LLM auto-resolution that lands without re-verification; `merge=union` on editable tables; workers rebasing themselves; agent-to-agent negotiation for file ownership.

## §2 Lauren Tan (@poteto)

### 2.1 Provenance

| Item | Status |
|---|---|
| "2,500 PRs" talk | Verified: X post Sep 21, 2026, ~38-minute video; in the talk she says ~2,000; The Neuron reports an August close of 2,462; self-reported, much maintenance and refactoring |
| Five-layer trust ladder | Verified via talk summaries (redreamality; ratstack.sh) |
| pstack | Verified: official Cursor plugin `cursor/plugins/pstack`, MIT, v0.15.x; community ports for Claude Code, Codex, OpenCode |
| "Code as a continuous stream" post | Verified (X status 2116191971714953262, quoted in OnixResearch/kiln issues, Oct 31, 2026) |
| Grok Bot role and memory mechanics | Verified from xAI's launch post and guides; VentureBeat |
| Seven-role "Bot Team" chart | Not verified |
| @0xg4tsby "60+ Grok Bots" post | Not found |
| x.com/0xcarnagee status | Not reconstructable |
| Bend LAWS/PROOF as her view; checker-speed claims | Contradicted/unverified: LAWS.bend/PROOF.bend is Bend 2's convention; Tan says formal methods are not her path; pstack has formal-verification skill generators |

### 2.2 The trust ladder, "push corrections up"

Strongest first: (1) codebase and architecture make the bad pattern impossible; (2) static analysis — lint, compiler, CI; (3) rules, Bugbot, skills — guidance an agent may forget; (4) style guides and human review — don't scale with PR rate; (5) verification skills prove correctness, not performance or quality; formal methods beyond that, not her path. Rule: when you chase an agent with the same correction, move it up a layer; the first reaction to a bad pattern is a lint rule; recurring review comments mean a concern is "stuck at layer four".

Vigil: partial — layer 2 (ruff/mypy/pytest), fresh-context reviewer (3–4), hidden-test verification (5); nothing promotes recurring findings into lint or architecture. Borrow: reviewer rule "tag the strongest layer that could have prevented it: ARCH | LINT | SKILL | STYLE; if the same finding appears in ≥2 prior rulings, emit PROMOTE: <lint rule or type change> as an inbox brief". CLAUDE.md line for target repos: "The codebase is memory: agents copy what they see. Never leave a workaround or explanatory hack comment; fix it or file it."

### 2.3 Verification skills that force evidence

Her first Cursor skill, "Control Glass" (internal): a reproducible CLI kept in the skill directory (scripts drift between sessions) that launches the app via the Chrome DevTools Protocol and collects traces and heap snapshots; plus an app "feature map" — on-disk memory of every feature, how to reach it, which DOM elements to click, maintained by automations. pstack merges require "a verifier verdict and green CI" (Tenten). Vigil: has test-based verification; lacks run-the-app evidence. Borrow: per-repo `verify/` CLI run by the verifier, not the worker; artefacts attached to the decision card. Tan's "feature map" is an app-navigation map; Vigil's `docs/feature-map.md` is a roadmap; keep separate.

### 2.4 pstack's files (verified from `cursor/plugins`)

Entry points `/poteto-mode`, `/poteto-help`, `/setup-pstack` (model per role, reasoning budget). Playbooks: bug fix (repro first), feature (behind a flag), investigation, babysit PR, swarm, overnight run, multi-phase plan (writes the plan, doesn't implement), orchestrate. Principle skills (one principle each): attack-the-premise, boundary-discipline, build-the-lever, encode-lessons-in-structure, model-the-domain, never-block-on-the-human, outcome-oriented-execution, prove-it-works, redesign-from-first-principles, separate-before-serializing-shared-state, sequence-verifiable-units, subtract-before-you-add, test-behavior-not-implementation, type-system-discipline. Workflow skills: how, why, interrogate, reflect, recall, swarm, arena, architect, unslop, automate-me (mines transcripts into a `<you>-mode` skill), make-bot-ui, formal-verification generators. `/deslop` is from cursor-team-kit. Not found: `/correct-style`, a TDD skill. poteto-mode asks for a dedicated subagent type, background runs, "file pointers not inlined context", explicit model per role; review skills use diverse-model review.

Borrow: worker skills prove-it-works, sequence-verifiable-units, subtract-before-you-add, separate-before-serializing-shared-state; diverse-model review (CONFIRMS Sonnet + Opus; consider a third model for risky shapes); a planner that doesn't implement (= coord). Skip automate-me-style mining until §4b rules exist.

### 2.5 Codebase as memory

Grok Bot's team built "Dune", an unpublished client framework: "agents love shortcuts, so make the shortcut the correct path"; locked down enough to be "annoying for humans"; comments banned because agents papered over bugs with them; the maintainer is the "gardener". Oct 30 post: code "written as if it were a continuous stream… make the easy thing the right thing… agent contributions grow around the constraints and guardrails you've designed." Vigil enforces boundaries around the worker, not inside target repos. Borrow: a readiness check before rung >0 (strict types, lint as errors, generated-files manifest, migrations dir). Don't adopt the comment ban wholesale; ban workaround comments (TODO/HACK without a ticket) via lint.

### 2.6 Parallelism only after trust

She starts at one to five supervised chats; 100 cloud agents without trust produce "garbage pull requests, regressions, and bugs"; the outer loop "only adds output when the repository is already worth copying." She eventually lets agents merge their own PRs overnight and reviews after landing. CONFIRMS Vigil's ladder by shape; CONTRADICTS on the end state (agent self-merge). Recommendation: keep "a human merges" for client and money paths permanently; post-merge review only at the top rung for narrow shapes with auto-revert, if ever.

### 2.7 Grok Bot mechanics (public)

"Your team of always-on agents" on a shared cloud computer, $120/month (VentureBeat). Roles defined by name, label, description; practitioners recommend each state "what it owns, what it's never allowed to do, and who it reports to". Memory and routines belong to each Bot and don't transfer. Chief of Staff is a usage pattern, not a feature ("one to manage the others"). "Named agents, separate memory"; an eng-manager Bot that "does not code". Every Bot message counts toward usage. Borrow: `owns / never / reports-to` in every role prompt; memory scoped per role. Don't adopt a Chief-of-Staff agent that dispatches on its own.

## §3 "Claude Duet" and the one-app question

- **Claude Duet** (announced Oct 21, 2026): standalone proactive-agent app (iOS, Android, claude.ai) on Opus 5.5, no model choice; research preview, waitlist, US Pro and Max; uses plan limits; carries over memory, skills, connectors (6,000+); checks connected accounts every few hours; asks before sending, paying, signing, deleting; runs in its own cloud VM. Built for inboxes and dashboards, not a coding factory; can't host a non-Claude advisor.
- **Claude Tag** (Jun 23, 2026): Slack-native, multiplayer, Opus 4.8; Team/Enterprise beta; Anthropic's product team gets 65% of code changes through it internally (Fortune). Wrong plan tier; decisions in Slack threads.
- **Claude Code Remote Control** (Feb 25, 2026, research preview): continues a local session from phone/web; execution stays local; outbound HTTPS only; one remote per session; terminal must stay open; ~10-minute outage ends the session; since ~Aug–Sep 2026 a `claude remote-control` machine shows as a device card for starting sessions from the phone. Ideal for coord.
- **Custom connectors (remote MCP):** all paid plans (Free gets one); connections come from Anthropic's cloud, so the server must be publicly reachable (tailnet-only fails); mobile uses connectors added on web; OAuth with DCR; Tailscale Funnel works on :443 (a :8443 attempt failed before OAuth, claude-ai-mcp #1146).
- **LibreChat:** MIT, v0.8.8 (Sep 30, 2026); MCP over stdio/SSE/Streamable HTTP, OAuth MCP, per-user isolated MCP, native OpenRouter; critical MCP CVEs (CVE-2026-32625 CVSS 9.6 server-secret exfiltration via MCP URL injection; CVE-2026-22252 stdio command execution) → pin versions, avoid stdio MCP.
- **Open WebUI:** v0.11.4; admin-only Streamable-HTTP MCP; branding clause above 50 users.

Recommendation: primary — Claude app + vigild MCP connector with read tools (`list_cards`, `get_card`, `job_status`, `budget_meters`, `rulings_search`) and one write tool `propose_brief`; coord in Claude Code with Remote Control; approvals on the Inbox over the tailnet, not the Funnel; `approve_card` on the connector only behind a second factor bound to the owner, if at all. Fallback — LibreChat on the Mac mini, tailnet-only, advisor on an OpenRouter model or tower Qwen, same facade and scope, calls through the gateway's caps. Don't adopt Claude Tag as the inbox or Duet as the control plane.

## §4 Vigil as a service; training on owner data; the feature map

### 4a Shipping with few reverts

- **Faros AI "Acceleration Whiplash" (2026; 22,000 developers, 4,000+ teams):** +242.7% incidents per PR (a ratio, not a probability); +57.9% monthly incidents; +28.7% bugs per PR; +31.3% PRs merged with no review; +51% PR size; +441.5% median review time; +861% churn; +54% bugs per developer; under 1% of PRs opened autonomously by agents; recommends tying definition of done to tests and enforcing PR size limits. CONFIRMS Vigil's no-unreviewed-merge rule and hidden-test verifier. No public agent-PR revert rate found; Vigil should measure reverts within 7 days per shape.
- **Post-merge watch and auto-revert:** Anthropic's per-component "superfan" agents watch telemetry (via kiln); GitHub Agent Merge fixes before merge. Adapt: a post-merge watcher runs smoke and `verify/` on main after each land; failure opens a revert PR and a card; the revert needs a human merge at rung 0.
- **Characterisation tests before refactors:** consistent with pstack's test-behavior-not-implementation; a `refactor` shape lands a tests-only PR first.
- **Readiness profiles:** no public playbook; adapt per repo: MVP (tests + lint), production (+ `verify/` evidence, flags for risky paths, post-merge watch), enterprise (+ migration dry-runs, licence scan, SBOM, two-reviewer rule).
- **Domain verifier plug-ins (inferred):** SaaS — migration up/down on a fresh snapshot, browser smoke with screenshots, API contract tests; automations — dry-run on recorded fixtures (no egress), idempotency by running twice; ML — data expectations, pinned dataset hash, held-out metric must not regress more than ε vs the logged baseline, notebook hygiene; AI — frozen goldens, eval cost through the gateway, LLM judge secondary only. Held-out eval data is the ML equivalent of hidden tests. EXTENDS Vigil.

### 4b Training and eval on employer or client repositories (not legal advice)

Ownership and confidentiality come first: code written for an employer or client is usually theirs; NDAs usually forbid sending it to third parties; a cloud model call or fine-tune can breach confidentiality regardless of copyright. US Copyright Office Part 3 (May 2025): training "will often be transformative" but not inherently fair use; pirated data weighs against. *Bartz v. Anthropic*: lawfully acquired books fair use, pirated library not; settled $1.5B (final approval Jul 20, 2026; ~482,460 works). *Kadrey v. Meta*: fair use for those plaintiffs (Jun 2025); other claims continue (hearing Feb 25, 2027). *Doe v. GitHub*: Ninth Circuit (Sep 16, 2026) affirmed dismissal of DMCA §1202(b) claims; licence and contract claims pending. Open-source licences: no FSF/OSI ruling that weights trained on GPL code are derivative; outputs reproducing GPL/AGPL code carry obligations; AGPL's network clause matters for SaaS; keep a licence scan in the verifier. GitHub terms (Apr 24, 2026): private repo content at rest not used for training; Copilot Free/Pro/Pro+ interaction data used by default with opt-out; Business/Enterprise excluded → opt out or use Business seats for client work. EU AI Act: GPAI obligations since Aug 2, 2025; Commission enforcement from Aug 2, 2026; a fine-tuner becomes a "provider" only if the modification uses more than ~one-third of the original training compute — personal/local fine-tunes almost certainly don't trigger it; offering a fine-tuned model to EU clients deserves a closer look.

Practical rule set: written consent naming purpose (eval vs training), model location, retention; train and evaluate on employer/client code only with tower-local models; `training_allowed` flag per repo, default false; provenance tag on every derived artefact; exclusion list (secrets, PII, vendored third-party code, AGPL code); no exfiltration (gateway blocks cloud providers for flagged repos; containers stay no-egress); datasets out of git (hashes and DVC-style pointers), deleted on contract end; never let a model trained on client A's code serve client B.

### 4c A streamlined feature map for one week

No public case studies of agent factories narrowing scope. Recommended: one goal with a pass/fail check ("10 consecutive Vigil PRs land with zero manual rebases"); rows that serve it, each with shape, scope globs, readiness profile, required evidence, status; cut a row if it doesn't reduce rebases, reverts or owner minutes this week, needs a new harness or model to be useful, overlaps a hot file leased by a higher-priority row, or can't name its verification evidence. This week's rows: landing queue + rebased-SHA verify; scope leases; generated docs tables; migrations serialisation; worker landing skill; reviewer PROMOTE rule; MCP facade with `propose_brief`. Defer: cockpit visuals, Grok Build spike, Cursor bridge expansion, training pipelines.

## Borrow / Adapt / Don't adopt

| Item | Verdict | Vigil component | Reason |
|---|---|---|---|
| vigild serial landing queue + rebased-SHA verify | Borrow | vigild, verifier | tests the exact tree that lands |
| Scope leases at dispatch | Borrow | coord, FSM | CooperBench: explicit division prevents the 33.2% overlap failure |
| Generated docs tables from per-row files | Borrow | repo, CI | removes the hottest conflict class |
| Serialised migrations (lease or timestamped files) | Borrow | vigild/db.py | ends add/add collisions |
| `merge=union` | Adapt | vault merge | append-only ledgers only |
| GitHub merge queue | Adapt (later) | ruleset | free; useful once merge rate is high |
| Graphite / Aviator / Trunk / Mergify | Don't adopt | — | paid, team-oriented, second decision surface |
| LLM conflict auto-resolve without re-verify | Don't adopt | vault | ~55–65% accuracy |
| 400-line diff budget | Borrow | verifier, worker skill | size correlates with conflicts and defects |
| Trust ladder "push corrections up" | Borrow | reviewer prompt, rulings | repeat findings become lint/types |
| Verification CLI + app map (evidence) | Borrow | verifier plug-in | proof beyond unit tests |
| pstack principle skills | Borrow | worker skills | small, routable |
| Diverse-model review | Borrow | reviewer/auditor | confirms Sonnet+Opus |
| Agent self-merge with post-hoc review | Don't adopt | ladder | conflicts with human-merges; Faros data |
| Comment ban (Dune) | Adapt | lint in target repos | workaround comments only |
| Bend LAWS/PROOF gates | Don't adopt now | verifier | not Tan's practice; immature for Python stacks |
| Role owns/never/reports-to blocks | Borrow | all role prompts | clear roles once; scoped memory |
| Autonomous Chief-of-Staff dispatcher | Don't adopt | coord | inbox is the sole decision surface |
| Claude app MCP connector (read + propose_brief) | Borrow | MCP facade | one-app ideation; Funnel :443 + OAuth |
| Claude Code Remote Control for coord | Borrow | coord | local execution, phone access |
| LibreChat + OpenRouter advisor | Borrow (fallback) | advisor, gateway | model-agnostic; metered |
| Claude Tag / Duet as control plane | Don't adopt | — | tier/waitlist; Claude-only |
| Post-merge watcher + revert PR | Borrow | vigild jobs | catches what pre-merge missed |
| Characterisation-tests-first refactor shape | Borrow | task shapes | pins behaviour before change |
| Readiness profiles | Adapt | verifier config | strictness by client need |
| ML/AI eval gates, data tests | Borrow | verifier plug-ins | held-out evals = hidden tests |
| Training on client code via cloud models | Don't adopt | router, gateway | confidentiality and licence risk |
| `training_allowed` flag + local-only training | Borrow | router rule 9, provenance | consent-gated, auditable |

## Sources (abridged; full list in the project copy)

AgenticFlict arxiv.org/pdf/2604.03551 · Xu et al. arxiv.org/html/2607.04697v2 · CooperBench iclr.cc/virtual/2026/10018463, alphaxiv.org/abs/2601.13295 · Anthropic Scion coverage xenospectrum.com/en/anthropic-scion-source-control-redesign/ · GitHub merge queue docs docs.github.com/.../managing-a-merge-queue · stacked PRs github.com/orgs/community/discussions/209892, infoq.com/news/2026/04/github-stacked-prs/ · queue comparisons menuagentic.com, dev.to/pyor, aviator.co, graphite.com · Faros pages.faros.ai/.../AI_Engineering_Report_2026_The_Acceleration_Whiplash_Faros.pdf · Copilot changelogs github.blog/changelog/2026-03-26-..., 2026-10-28-agent-merge-... · union-merge threads gitlab foodsharing #1014, ferret-scan #781, pandas-ta-classic #155, ripr-swarm #5069, KTPInfrastructure #378, keep-a-changelog #56 · Shen arxiv.org/pdf/2607.27674 · Gmerge microsoft.com/.../issta22-merge-conflicts-llm.pdf · Tan talk summaries redreamality.com, ratstack.sh, developer.tenten.co, atlasnote.ai · pstack github.com/cursor/plugins/tree/main/pstack · Tan post x.com/poteto/status/2116191971714953262 (via OnixResearch/kiln issues #24, #27) · Grok Bot x.ai/news/introducing-grok-bot, x.ai/bot/guides/grok-bot-for-pms, venturebeat.com · Claude Duet macrumors.com, techcrunch.com (Oct 21–22, 2026) · Claude Tag anthropic.com/news/introducing-claude-tag, fortune.com · Remote Control helpnetsecurity.com (Feb 25, 2026) · custom connectors support.claude.com/en/articles/11503834, github.com/anthropics/claude-ai-mcp/issues/1146 · LibreChat/Open WebUI wz-it.com, vdf.ai · legal: copyright.gov Part 3 coverage (sidley.com), Bartz settlement coverage, Kadrey scheduling order, Doe v. GitHub Ninth Circuit coverage, EU AI Act GPAI guidelines.

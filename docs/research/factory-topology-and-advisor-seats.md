# Make factories projects, keep advisors strong (2026-11-01)

Unverified sources per ADR-0006. Produced by a research task for the owner from the plan `claude/research/factory-topology-research-plan.md` in the Vigil project; committed as the owner supplied it. Vendor-reported numbers are marked VENDOR, unchecked claims **[unverified]**, the report's own reasoning **[inferred]**. The "Vigil facts" it read came from a read-only checkout at `/tmp/vigil-main`; the in-house evidence it lacked is in `docs/research/factory-topology-evidence.md` (#266). Rulings R29–R33 adopt its recommended options.

**Bottom line.** Four of the five candidate positions hold up. One needs a real correction. The market has settled on a unit that holds several repos. Warp names that unit a "factory" and gives the same sizing rule D1 proposes: "Group repositories that ship together into one factory, and keep separate products in separate factories" ([Warp](https://docs.warp.dev/factories/)). D1 is confirmed. D2's shape (a default seat, an optional seat per conversation, scope fixed by the seat and not by the model) is the mainstream pattern and is confirmed. The evidence goes against making a cheap or local model the *default* advisor. Every product that splits roles puts the stronger model in the advice seat. Anthropic's API refuses a weaker advisor outright ([Claude API docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool)). The one controlled study that tests both directions found that "a weak planner hurts performance much more than a weak executor" ([arXiv 2510.07505](https://arxiv.org/pdf/2510.07505)). D3 is right about layering, tighten-only and provenance, but wrong to make "nearest wins" the general rule: every mature policy system uses per-key merge kinds, where nearest-wins is one kind among several. D4 is confirmed, with one gap: on a unified KV pool a reserved slot does not reserve memory. D5 is confirmed but too short; it needs requested versus served model, provider, prompt version, session ID and approver. Two in-house conflicts matter more than any outside finding. First, ruling R22 and item p3-23 already use "factory" for a *config blueprint*, while D1 redefines it as a *project*. Second, experiment #37 as drafted runs two factories on one repo, which D1 forbids. This report resolves both, gives ruling cards R29–R33 and redesigns #37 so it can produce a verdict in two weeks.

Sourcing conventions: vendor-measured numbers are marked VENDOR. A claim this research could not check against a primary source is marked **[unverified]**. A claim that is my own reasoning, not a source's, is marked **[inferred]**. Vigil facts come from the read-only checkout at `/tmp/vigil-main`.

## Verdicts at a glance

| # | Candidate position | Verdict | Core evidence |
|---|---|---|---|
| D1 | Factory = one project of ≥1 repos; exactly one factory per repo; floors above | **Confirms** (multi-repo unit). **Extends** (exactly one factory per repo is stricter than any product, and nothing contradicts it) | Warp factories, Codex Cloud, Cursor Cloud Environments, Devin orgs |
| D2 | Default seat + optional per-conversation seats; always advisor scope, never approve | **Confirms** (shape, scope bound to the seat). **Contradicts in part** (a cheap default advisor). **Extends** (backend intersection, loud fallback, critic, per-seat standing classes) | Claude Code `/advisor`, Copilot BYOK, Amp oracle, PEAR, Anthropic pairing floor |
| D3 | Global → floor → factory → repo → task shape, nearest wins; caps only tighten; effective-config view; config as code | **Confirms** (layers, tighten-only, provenance, code). **Contradicts** ("nearest wins" as the general rule). **Extends** (merge kind per key, stored provenance, evaluate mode, temporal tighten-only) | Claude Code settings, GitHub rulesets, Cedar, `git config --show-origin` |
| D4 | Shared tower and gateway; advisor priority at admission via a reserved slot; no mid-stream preemption; per-factory budget lines | **Confirms** (admission, no preemption). **Extends** (KV reservation, prefill gate, tower fair share separate from dollars) | llama.cpp slots and unified KV, vLLM recompute preemption, LiteLLM admission queue |
| D5 | (floor, factory, seat/role, model, harness) on every row; `/factories` view | **Confirms. Extends** to a 12-field tuple | OTel GenAI conventions, GitHub agentic audit log, Langfuse |

## Units now hold several repos, and Warp already calls them factories

Hosted products disagree on names but agree on shape. Expensive shared state (environment, repo access, budget) sits on a unit above the repo, and instructions live at repo level. A Devin organization is "a self-contained unit with its own environment, repo access, and members," with ACU limits per org and guidance that "teams that regularly work on the same codebase should usually share an org" ([Devin](https://docs.devin.ai/enterprise/getting-started/organizations)). On 2026-09-29 Codex Cloud began letting users **select multiple GitHub repositories when creating an environment**, and single-repo environments are now labelled "Legacy" ([Developers Digest](https://www.developersdigest.tech/blog/codex-cloud-reusable-environments)). Cursor started 2026 with single-repo cloud agents and spent the year fielding multi-repo complaints. By August it had multi-repo Cloud Environments, which users called "incredibly strange and unusable on several levels" because selecting several repos often set up only one ([Cursor forum](https://forum.cursor.com/t/cursor-cloud-environments/169121)). Warp's factory-as-code is the closest analogue to D1: `factory.yaml` carries `name`, `repositories` and `agentDefaults`, and a foreman is "the only default agent that communicates directly with you" ([Warp](https://docs.warp.dev/factories/factory-as-code/); [Warp agents](https://docs.warp.dev/factories/factory-agents/)). Warp also states the rule that "the factory never merges on your behalf" ([Warp](https://docs.warp.dev/factories/)).

No product documents an *exactly-one-unit-per-repo* rule, and none contradicts one. Devin comes closest by accident: each org has **one active snapshot**, and when repos in one snapshot conflict, "the last one to run wins" ([Devin blueprints](https://docs.devin.ai/onboard-devin/environment/blueprints)). That hazard is the argument for D1's uniqueness rule and for a factory-level base layer that repo layers cannot override. Vigil's per-repo dev images already provide that base layer. Many *agents* per repo is normal everywhere: Copilot's `.github/agents/`, Claude Code's subagent hierarchy, Warp's profiles ([GitHub](https://docs.github.com/en/enterprise-cloud@latest/copilot/concepts/agents/cloud-agent/about-custom-agents); [Claude Code](https://code.claude.com/docs/en/sub-agents)). The question of many units per repo has no documented answer. The verdict is **confirms** on multi-repo, and on uniqueness, **extends**: Vigil's rule is stricter than any product, at no cost the evidence shows.

The bigger D1 problem is internal. R22 defines "factories are the configs a line is built from," p3-23 puts those configs in `configs/factories/<name>.yaml`, R27 makes experiment arms "factory-config revisions," and the `/factories` page shows a scoreboard per (model, harness, template). D1 instead makes a factory the project. Meanwhile p3-03 and p3-13 add a separate `projects` table whose `repo` column holds a single repo. Left alone, Vigil ends up with three overlapping nouns. **[inferred]** The clean resolution: the factory *is* the project, so `projects` becomes `factories`, with a `factory_repos` join table and a unique index on `repo`. The blueprint R22 called a factory becomes a **profile** inside the factory file, keyed by task shape, and R27's arms become profile revisions. "Floor" has the same collision: R22 uses "the watch floor" for the home view, while §18 uses floors for tenancy (`floor_id` beside `project_id`). R29 should name one of them differently. The simplest fix keeps *floor* for tenancy and keeps the home view's nav label "Watch Floor" as a page title, never as a data noun.

## Seats bind scope well, but the evidence puts strong models in them

D2's structure is the market norm. GitHub Copilot's chat picker takes BYOK models, including local Ollama endpoints, and org admins can disable BYOK, which is off by default for Business and Enterprise ([Start Debugging](https://startdebugging.net/2026/04/github-copilot-vs-code-byok-anthropic-ollama-foundry-local/)). Claude Code offers an `advisorModel` default plus `/advisor` and `--advisor` per session, all inside the org's `availableModels` ([Claude Code](https://code.claude.com/docs/en/advisor)). Binding scope to the seat rather than the model also has precedent. Anthropic's advisor "runs without tools" whichever model fills it ([Claude API docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool)). Amp fixes the oracle's role and changes its model ([Amp](https://ampcode.com/news/gpt-5.4-the-new-oracle)). One Claude Code detail warns against relying on permission modes: a parent in bypass or auto mode overrides a subagent's `permissionMode` ([Claude Code](https://code.claude.com/docs/en/sub-agents)). Advisor scope therefore has to be a vigild token property (R2's advisor token: read, `propose_brief`, `wait_for`, never `inbox_act`). It cannot be a harness setting.

The cheap-default idea fails on evidence. Every shipping split puts the stronger model in the planning seat: Anthropic's advisor tool, Amp's oracle, Claude Code's `opusplan`, Cursor plan mode with cheap explore subagents. Anthropic enforces the direction: the advisor "must be Sonnet 4.6 or more capable," invalid pairs return HTTP 400, and Haiku "can call the advisor but can't act as one" ([Claude API docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool); [Claude Code](https://code.claude.com/docs/en/advisor)). PEAR measured both directions on 84 tool-use tasks (not coding). With Gemini-2.0-flash as planner, utility was about 30%. A strong planner with the same weak executor stayed near 48–69, and a GPT-5 planner held 68–72 whatever the executor ([arXiv 2510.07505](https://arxiv.org/pdf/2510.07505)). The measured gains from a *strong* advisor are modest, VENDOR, and not like-for-like: +2.7 pp at −11.9% cost on SWE-bench Multilingual for Sonnet 4.6 with an Opus 4.6 advisor ([Anthropic](https://claude.com/resources/articles/the-advisor-strategy)). The cleanest public split datapoint is 20 months old: an R1-architect plus Sonnet-editor pair scored 64.0% for $13.29, against 64.9% for $36.83 from the best solo model ([Simon Willison](https://simonwillison.net/2025/Feb/25/aider-polyglot-leaderboard/)). That is a *strong* reasoner planning.

Three findings bear directly on the tower's Qwen3.6-35B-A3B. A 35B-class judge (Qwen3.5-35B) checking a 122B model's code gained **+14.0 pp macro-F1 with an independent critic**; 20B and 4B judges gained nothing significant ([arXiv 2605.27483](https://arxiv.org/pdf/2605.27483)). So 35B sits at the threshold where structure helps. Practitioners running Qwen3.6 35B-A3B on 48–64 GB Macs use it the opposite way from #37's plan: "a bigger model plan[s] and then hand[s] small, straightforward tasks to the local model" ([martinfowler.com](https://martinfowler.com/articles/exploring-gen-ai/local-models-for-coding-experiences.html)). Small models are also badly sycophantic: 7–8B models flipped code-quality verdicts 38–72% of the time under a biased prompt, and evidence-guided prompts cut that to 12.5–46.3% ([arXiv 2607.10411](https://arxiv.org/pdf/2607.10411)). No source measures any open-weight model as a planner or brief writer for coding. That gap is the honest state of the evidence.

Vigil's design does offer real mitigation. PEAR's planners fed executors directly. Vigil's advisor feeds the owner, then the builders, then a verifier the advisor cannot touch. A mediocre brief therefore costs owner minutes and rejected cards, not silent merges. **[inferred]** Owner approval does not mitigate sycophancy, because the owner's framing is the bias source. Prompt injection is the other risk: in PEAR, planner-side compromise reached **82–89% harmful attack success**, against "consistently less effective" executor-stage attacks ([arXiv 2510.07505](https://arxiv.org/pdf/2510.07505)). The advisor reads issue bodies and logs, so `packets.fence()` and the absence of any write or exfiltration tool are the first line, and approval is the second. One D2 element weakens this mitigation: p3-58's **standing brief classes**, which auto-approve matching briefs with no owner action. A cheap seat that is not yet trusted, under a standing class, removes the human the whole argument depends on. Standing classes must therefore be granted per seat, and only to a seat that has graduated on Vigil's own metrics.

Three further extensions. First, a seat in a multi-repo factory reads every repo in it, so its allowed backends are the **intersection** of those repos' `backends` lists in `configs/repos.yaml`. A private repo restricts the whole factory's seats to what the private-repo rule allows. Second, Claude Code drops a refused advisor silently ("you see no error and get no advisor calls") ([Claude Code](https://code.claude.com/docs/en/advisor)). Vigil seats must record requested and served model per turn and fail loudly. Third, per the owner's terms constraint, a subscription-backed seat must be the unmodified Claude Code binary signed in by the owner. In practice that means the Claude app through the facade, or a `/talk` lane that vigild launches as a Claude Code session, as R17's coord lane already is. Any other harness on a Claude model uses an API key through the gateway. **[unverified]**: this research did not re-check the consumer terms; the constraint is taken as given.

## Nearest-wins holds for defaults, but policy needs a merge kind per key

Claude Code is the closest analogue to D3 and the best warning against it. Its precedence stack is managed, then CLI, local, project, user, but the managed (org) layer sits at the *top*, so for policy the farthest layer wins: "Nothing in your own settings files or `--settings` overrides a managed key" ([Claude Code settings](https://code.claude.com/docs/en/settings)). Lists merge by union. Permissions evaluate deny, then ask, then allow across every scope, so "a user-level deny blocks a project-level allow" ([Claude Code permissions](https://code.claude.com/docs/en/permissions.md)). A curated set of security keys takes the strictest value from any scope, and for `maxEffortLevel` "the lowest cap applies." Allowlists such as `availableModels` are taken whole from the top source, because a union of allowlists loosens them ([managed settings](https://code.claude.com/docs/en/managed-settings.md)). Loosening keys in repo files apply only after the folder is trusted, while "`deny` and `ask` rules apply right away" ([Claude Code settings](https://code.claude.com/docs/en/settings)). Claude Code accumulated this through a hand-kept exceptions table that grew release by release. Vigil should declare merge kinds in the pydantic model from the start. Policy systems outside Claude converge on the same answer. A GitHub ruleset "does not have a priority": when rules conflict, "the most restrictive version of the rule applies" ([GitHub](https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)). In Cedar, forbid overrides permit, and the result does not depend on policy order ([Cedar](https://docs.cedarpolicy.com/auth/authorization.html)). Nearest-wins is correct only for defaults and preferences.

Provenance has a gold standard and a gap. `git config --show-origin --show-scope` prints the file and scope of every value ([git-config](https://man.cx/git-config)). Claude Code's `/status` "doesn't show which file supplied each key" ([Claude Code settings](https://code.claude.com/docs/en/settings)). Vigil should store each job's effective config hash and per-key origin on the job row, so `vigil config explain <job>` is historical rather than recomputed. Managed Agents shows why: its environments "are not versioned," so users must track per session which config ran ([Claude Platform](https://platform.claude.com/docs/managed-agents/environments)). Three more patterns are worth taking. GitHub's Evaluate mode and Kubernetes `[Warn, Audit]` give a dry-run stage for a new policy key ([GitHub](https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets); [OneUptime](https://oneuptime.com/blog/post/2026-02-09-cel-admission-policies-replace-webhooks/view), secondary, **[unverified]** against kubernetes.io). Kubernetes `oldObject` transition rules make tighten-only temporal: a PR may lower a cap, but raising one needs owner approval. Terraform's health checks detect drift without auto-remediating ([HashiCorp](https://developer.hashicorp.com/terraform/enterprise/v202502-2/workspaces/health)). On failure, Claude Code refuses to start on an unparseable managed document and reads invalid restrictive keys as their restrictive value ([managed settings](https://code.claude.com/docs/en/managed-settings.md)). Vigil should go further and refuse to start on *any* invalid policy key, since it runs on one owned host.

One Vigil-specific rule follows **[inferred]**: no layer that a worker or model can write may loosen anything. The task-shape layer is chosen in a spec that a coord drafts, and repos contain files that workers write. Both can only tighten. A target repo's tree is never read as a config source.

### Schema sketch: `configs/factories/<name>.yaml`

```yaml
schema: 1
name: vigil                         # unique; file name must match
floor: home                         # top-only: must match configs/floors.yaml
repos: [thomasbardhi01/vigil]       # unique across all factory files (CI) and in DB (unique index)
budget:                             # merge: min (against floor and global)
  monthly_usd: 140.00
  daily_usd: 18.00
  per_task_usd: 2.00
tower:                              # local capacity, separate from dollars
  share: 0.6                        # fair-share weight of the worker pool; sum over factories normalised
  max_sessions: 2                   # min
advisor:
  scope: advisor                    # top-only constant; any other value is a CI error
  default_seat: claude-app
  seats:
    claude-app:
      surface: mcp-facade           # p3-51; the owner's Claude app, subscription, not gateway-metered
      harness: claude-app
    talk-sonnet:
      surface: talk
      harness: vigil-room
      backend: claude-sonnet        # intersection: must be in every repo's backends
      session_usd: 0.50             # min; metered by the gateway like any task
    talk-tower:
      surface: talk
      harness: vigil-room
      backend: tower-qwen
      propose_shapes: [fix-S, tests, docs, deps, lint]   # intersection
      forbid_paths_from: ladder_pinned_paths             # union with money_paths
      critic: claude-sonnet         # one independent critique before the card
      evidence_citations: required  # strictest
  standing_classes: {}              # per seat; empty until the seat graduates (R2, p3-58)
profiles:                           # what R22 called "factory configs": per shape
  default: {harness: claude-code@2.1.306, coord: claude-opus, reviewer: claude-sonnet}
  fix-S:   {coord: claude-sonnet, per_task_usd: 1.00}
```

| Key kind | Vigil keys | Merge rule | Precedent |
|---|---|---|---|
| Defaults | `default_seat`, profile models, prompt variant, timeouts | override, nearest wins | Claude Code scalars; git last-wins |
| Money and capacity caps | `*_usd`, `max_sessions`, `session_max_output_tokens`, `wip_per_repo` | min across all layers | `maxEffortLevel` |
| Floors | verifier runs, required reviewers, ladder rung minimum | max | GitHub "most restrictive" |
| Denylists | `forbid_paths`, denied tools, denied hosts | union | `permissions.deny` |
| Allowlists | seat `backend`, `propose_shapes`, egress hosts, token permissions | intersection; a child that adds an entry is a CI error | `availableModels` whole-from-top; Cedar default deny |
| Boolean locks | `evidence_citations`, sandbox, no-network | strictest | Claude Code lock keys |
| Top-only | `floor`, `advisor.scope`, private-repo backend rule, provider keys, provenance policy | global or floor only; set lower → CI error | `defaultMode` top-only; `vigild/repos.py` hard-coded list |
| Atomic groups | `backend` + `key_ref` + `base_url` | taken whole from one layer | Claude Code telemetry unit |

CI checks child ⊆ parent for every monotonic key, and new ≤ old unless the owner approves the PR. `vigil doctor` compares the loaded-config hash with the hash of `configs/` at `origin/main`.

## The tower needs a KV reservation, not just a slot

llama-server has slots, a unified KV pool, per-slot prompt caches and slot pinning (`id_slot`). It has no request priority and no mid-stream preemption. The only PR titled "preemptive priority scheduling" covered router-mode model loading, and it was closed ([PR #22851](https://app.semanticdiff.com/gh/ggerganov/llama.cpp/pull/22851/overview)). With `--kv-unified`, "one long conversation can crowd out short ones" ([Multigrid](https://dev.to/multigrid/serving-parallel-requests-with-llamacpps-server-slots-c90)). A free slot does not guarantee free memory. When slots are busy, requests are deferred, and an open fairness bug lets a deferred task wait behind newer arrivals "forever" ([issue #15008](https://github.com/ggml-org/llama.cpp/issues/15008)). The alternatives are heavier. vLLM's `priority` policy preempts by recomputation by default ([vLLM](https://docs.vllm.ai/en/v0.10.2/api/vllm/config/scheduler.html)), which means re-prefilling a 60–100k agent context on consumer cards. LiteLLM's priority queue is beta and admission-only ([LiteLLM](https://docs.litellm.ai/docs/scheduler)), and vigild's gateway already does that job. Kubernetes `preemptionPolicy: Never` (queue-jump without eviction) is the right model for D4 **[unverified this session against kubernetes.io]** ([Kubernetes](https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/)).

Vigil already has most of the machinery. `vigild/scheduler/capacity.py` reads `/props`, gates sessions on slot count, and keeps live reservations within `n_ctx − 8192`, with each session reserving its expected peak (floored at 32,768). The 8,192 headroom is a safety margin and nobody owns it. The D4 extension **[inferred]**: give the advisor a named reservation R (for example 24k, sized from the advisor's own peak) that worker admission can never claim. Pin the advisor to one slot with `id_slot`, which also keeps its prompt cache warm. Set `-np` to the admitted workers plus one. Never send more concurrent requests than there are slots, so llama-server's deferral queue goes unused. Admit at most one large uncached prefill at a time, because prefill interference, not slot shortage, is what will spike advisor time-to-first-token. Indicative data: on an RTX 4090, llama.cpp went from 49.5 tok/s alone to 12.6 tok/s per request at 32 concurrent requests, with 6.5 s TTFT ([computingforgeeks](https://computingforgeeks.com/ollama-vs-vllm-vs-llama-cpp/); the article's version labels are odd, so treat the numbers as indicative). Nothing measures this on 2×5070 Ti with this model, so #37 has to. Per-factory budget lines fit p3-13's gateway project cap, with `min` merging under the global $200 monthly and $25 daily pacing caps. Dollars cover hosted calls only, so each factory also needs a tower share (a fair-share weight over the worker pool) and an advisor-wait SLO.

## Twelve fields answer "who did this, for which factory, on which model"

D5's five fields match the OpenTelemetry GenAI vocabulary and GitHub's audit model, but miss what those sources treat as essential. OTel separates `gen_ai.request.model` from `gen_ai.response.model`, because "the model you asked for and the model that served the request are not always the same," and requires `gen_ai.provider.name` ([Dash0](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained), secondary). Every `gen_ai.*` attribute is still at **Development** status, and since v1.42.0 the conventions ship from a separate repo with no tagged release ([Dash0](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained); [DEV](https://dev.to/azena-ai/opentelemetrys-genai-semantic-conventions-are-not-stable-yet-heres-what-actually-shipped-in-2026-3mke)). The two secondary sources disagree on whether `gen_ai.conversation.id` is conditionally required **[unverified]**. Vigil should keep its own column names and map them at export, which it needs anyway because Phoenix speaks OpenInference. GitHub's agentic audit log carries `actor_is_agent`, `agent_session_id` and the initiating `user`, but **no model field** ([GitHub Docs](https://docs.github.com/en/copilot/reference/enterprise-administrators/agentic-audit-log-events)). Commits carry an `Agent-Logs-Url` trailer ([GitHub changelog](https://github.blog/changelog/2026-03-20-trace-any-copilot-coding-agent-commit-to-its-session-logs)). Squash merges drop trailers ([agentpatterns.ai](https://agentpatterns.ai/workflows/agent-commit-attribution/)), so attribution must live in Vigil's DB, keyed by SHA.

The recommended tuple is `(provenance, floor, factory, seat, harness@version, provider, model_requested, model_served, prompt_ref, session_id, job_id, approved_by)`, plus an optional `parent_session_id` (advisor → brief → job chain) and `config_ref` (the effective-config hash). `provider` is the field the private-repo rule depends on. `approved_by` carries `standing:<class>` when p3-58 auto-approves. Langfuse filters only on top-level keys ([Langfuse](https://langfuse.com/integrations/native/opentelemetry.md)), so all fields are flat columns. `/factories` rows are factory × seat, with model served (flagged when it differs from requested), harness@version, spend against the factory line, and quality (brief approve-unchanged rate, verifier pass delta). The orb's per-backend ring needs a text label, because Vigil's UI rule is that state is "a word plus a glyph, never colour."

## Adopt and do not adopt

| Adopt | From |
|---|---|
| Factory = multi-repo project with `repositories` + defaults in one file; foreman-like single conversational seat; global inbox across factories | Warp factory-as-code, Warp dashboard |
| Unique repo membership plus a factory base layer repo layers cannot override | Devin's "last one wins" hazard, inverted |
| Advisor scope as a token property, not a harness mode | Claude Code parent-override hazard; R2 |
| Per-key merge kinds; allowlists intersect; deny wins across layers; top-only keys | Claude Code settings, GitHub rulesets, Cedar |
| Stored per-key provenance; `vigil config explain`; evaluate mode; drift hash in `vigil doctor` | git `--show-origin`, GitHub Evaluate, Terraform health |
| Admission priority, advisor KV reservation, pinned slot, prefill gate | llama.cpp slots, Kubernetes `preemptionPolicy: Never` |
| Requested vs served model, provider, prompt version, session ID, approver | OTel GenAI, GitHub audit log, Langfuse |
| One independent critic pass and evidence-cited claims for a cheap seat | arXiv 2605.27483, arXiv 2607.10411 |

| Do not adopt | Why |
|---|---|
| A cheap or tower model as the default advisor before Vigil's own data | Every vendor and the only two-direction study point the other way |
| Silent advisor fallback | Corrupts the seat label; Claude Code's documented behaviour |
| Anthropic's advisor tool with 5-series advisors inside sessions | Returns encrypted `advisor_redacted_result` the client cannot read, so it breaks provenance ([Claude API docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool)) |
| vLLM or SGLang migration for priority preemption | Gives up GGUF/MoE flexibility for recompute costs on long contexts |
| LiteLLM's priority queue | Beta, and a second way to do what the gateway does |
| `gen_ai.*` names as DB columns | Development status, still renaming |
| Union-merged allowlists or "nearest wins" for caps | Loosens by construction |
| Repo-tree config files as a config source | Worker-writable |

## Ruling cards

**R29 — What a factory is.** Option A: factory = project of ≥1 repos, unique repo membership enforced in CI and by a DB unique index; `projects` becomes `factories`; R22's blueprints become per-shape *profiles*; "floor" is reserved for tenancy. Option B: keep R22 (factory = config blueprint) and add projects beside it. Option C: factory = repo, one-to-one. **Recommend A.** B leaves three overlapping nouns, and C repeats Cursor's single-repo year. *Confidence: high on the multi-repo unit and uniqueness; medium on the profile rename, since only R22 and p3-23 text depend on it.*

**R30 — Where advisor seats attach.** Option A: seats per factory, default plus optional per conversation; scope fixed by token; backends are the intersection over the factory's repos; requested and served model recorded and fallback refused; strong default seat; standing classes granted per seat after graduation. Option B: one global advisor (the Claude app) with a model picker in `/talk`. Option C: A with a tower seat as default for maintenance. **Recommend A.** C is the hypothesis #37 tests, not a ruling. *Confidence: high on scope and allowlist; medium on the strong default, because no study measures advisor quality for brief writing.*

**R31 — Configuration layering.** Option A: five layers, merge kind declared per key in pydantic, worker- or model-writable layers tighten only, stored provenance, evaluate mode, temporal tighten-only in CI, fail closed on any invalid policy key. Option B: nearest-wins plus a list of locked keys. Option C: flat per-factory files, no inheritance. **Recommend A.** B is the exceptions table Claude Code has had to grow release by release. *Confidence: high.*

**R32 — Sharing the tower and gateway.** Option A: admission priority, an advisor KV reservation R and pinned slot, at most one large prefill at a time, no preemption, per-factory dollar lines (`min` under global) plus a tower fair-share weight, and an advisor TTFT SLO. Option B: A without per-factory tower share (one FIFO). Option C: move to vLLM priority preemption. **Recommend A**, with pause-new-admissions as the only escalation when the SLO is breached. *Confidence: high on admission over preemption; medium on R's size and the prefill gate until #37 measures them.*

**R33 — Who-is-who.** Option A: the 12-field tuple on every row and event, Vigil column names mapped to OTel and OpenInference at export, `config_ref` on jobs. Option B: D5's five fields. Option C: OTel spans only. **Recommend A.** *Confidence: high; the exact OTel requirement levels are unverified but do not change the columns.*

## Experiment #37, redesigned: test seats inside one factory, topology across two repos

The draft has four defects. It runs `vigil` and `vigil-maint` on the same repo, which R29 forbids, and its fallback outcome ("one factory per repo with seats chosen per chat") is just R29 itself. Its keep criterion, maintenance $ per merged PR at least 30% below `vigil`'s, mixes up task mix with seat effect. Maintenance tasks are cheaper anyway, and advisor tokens are a small share of builder spend **[inferred]**. The Claude-app seat spends subscription, which the gateway never sees, so its dollars read as zero. And two weeks will not produce enough briefs. Detecting a 70% versus 50% approve-unchanged rate at α = 0.05 and 80% power needs about **93 briefs per arm** (two-proportion normal approximation) **[inferred]**.

The redesign splits the question into two arms under one budget line.

**#37a, seats (within factory `vigil`).** Maintenance-class requests (shapes fix-S, tests, docs, deps, lint) go to seats by block randomisation in vigild. Arm S is the strong seat: the Claude app via the facade, or `talk-sonnet` when the request starts in `/talk`. Arm C is `talk-tower` on Qwen3.6-35B-A3B with evidence-cited claims and one Sonnet critic pass. Arm C may not propose on `ladder_pinned_paths` or money paths, and neither arm has a standing class. Measures per seat: owner minutes per merged PR (p3-41's metric), brief approve-unchanged rate, edit size, reject rate, reversed advice (#35), first-attempt verifier pass of approved briefs' jobs, and advisor cost. Advisor cost covers gateway dollars, plus critic dollars, plus subscription-window share for the app seat, read the way p3-60 reads `claude-sub`. The owner grades by approving and editing, so no LLM judge is involved (R27).

**#37b, topology.** A second factory with a *disjoint* repo. The p3-63 Rust template repo is the natural candidate if it exists by then **[inferred]**. ParkAgent is excluded because it runs only through vigild after owner confirmation and lists no tower backend. Measures: config mistakes (any job whose stored effective config differs from what `vigil config explain` resolves for its factory and shape, plus a planted over-cap child that CI must reject), per-factory line refusals in a planted test, the tower's advisor wait and TTFT p50/p95 split by concurrent worker prefills, `requests_deferred` (target 0), and KV high-water mark.

| Outcome | Rule |
|---|---|
| Kill arm C at once | Any approved C brief leads to a revert within 7 days or touches a pinned or money path; or after ≥15 briefs per arm, C's reject-plus-heavy-edit rate exceeds S's by ≥20 pp |
| Continue C (not adopt) | Approve-unchanged within 10 pp of S and owner minutes per merged PR no more than 20% worse; extend to ~93 per arm |
| Adopt C as maintenance default | At ~93 per arm, the lower 90% bound of (C − S) approve-unchanged is above −10 pp, owner minutes no worse, advisor cost per approved brief lower |
| Keep topology | Zero config mistakes, the planted loosening rejected, advisor TTFT p95 within an SLO set from a baseline week (placeholder 5 s **[inferred]**), workers' queue wait no more than 20% above baseline |
| Simplify topology | Any config mistake or SLO breach that R and the prefill gate cannot fix: one factory, seats per chat |

## Gaps and unverified items

The in-house evidence coord was to gather (jobs and spend by repo, #217 admission records, #35 baselines) was not in this research's inputs, so R32's reservation size and #37's baselines are open. Primary pages could not be fetched for the llama.cpp server README (`--slot-save-path`, `--cache-reuse`, `--context-shift`), kubernetes.io, Slurm, Factory.ai (moved to docs.factory.com), Aider's 2024 architect table, or the OTel semconv repo. Kubernetes and OTel facts come from secondary sources. No source measures any open-weight model as a brief writer, advisor TTFT under concurrent long prefill on llama.cpp, or a strong executor's rate of correctly rejecting bad advice. Whether any product allows one repo in two units is undocumented. Customer claims in Anthropic's advisor post carry no N.

## Conclusion

The research changes the question #37 should ask. "Is a cheap advisor good enough?" is the wrong question, because the outside evidence says no as a default and cannot say more. The right question is whether Vigil's structure — owner approval, fenced input, a verifier the advisor cannot reach, a critic pass — turns a 35B advisor into an acceptable *maintenance* seat, as measured by owner minutes and edits on Vigil's own work. That needs about three months of maintenance briefs, not two weeks, so two weeks can only kill arm C, never adopt it. The topology question is cheaper and nearer. Most of its risk is naming and merge semantics, not compute, and R29 and R31 settle it on paper before p3-23 writes a line.

The one place Vigil leads the market is that it can make seat quality a measured, per-factory number. No surveyed product records which advisor produced a plan, whether the human kept it, and whether the hidden tests later passed. The twelve-field tuple and the stored effective config are what make that measurable.

## Sources

- Warp Factories overview: https://docs.warp.dev/factories/
- Warp factory-as-code: https://docs.warp.dev/factories/factory-as-code/
- Warp factory agents: https://docs.warp.dev/factories/factory-agents/
- Warp environments: https://docs.warp.dev/agent-platform/cloud-agents/environments
- Devin organizations: https://docs.devin.ai/enterprise/getting-started/organizations
- Devin blueprints: https://docs.devin.ai/onboard-devin/environment/blueprints
- Codex Cloud reusable environments (third-party): https://www.developersdigest.tech/blog/codex-cloud-reusable-environments
- Cursor Cloud Environments thread: https://forum.cursor.com/t/cursor-cloud-environments/169121
- Cursor plan-mode model switching: https://forum.cursor.com/t/model-switching-during-plan-mode/160593
- GitHub custom agents: https://docs.github.com/en/enterprise-cloud@latest/copilot/concepts/agents/cloud-agent/about-custom-agents
- GitHub agentic audit-log events: https://docs.github.com/en/copilot/reference/enterprise-administrators/agentic-audit-log-events
- GitHub Agent-Logs-Url changelog: https://github.blog/changelog/2026-03-20-trace-any-copilot-coding-agent-commit-to-its-session-logs
- GitHub rulesets: https://docs.github.com/en/enterprise-cloud@latest/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets
- Claude Code settings: https://code.claude.com/docs/en/settings
- Claude Code permissions: https://code.claude.com/docs/en/permissions.md
- Claude Code managed settings: https://code.claude.com/docs/en/managed-settings.md
- Claude Code subagents: https://code.claude.com/docs/en/sub-agents
- Claude Code advisor: https://code.claude.com/docs/en/advisor
- Claude API advisor tool: https://platform.claude.com/docs/en/agents-and-tools/tool-use/advisor-tool
- Anthropic, "The advisor strategy" (VENDOR): https://claude.com/resources/articles/the-advisor-strategy
- Claude Managed Agents environments: https://platform.claude.com/docs/managed-agents/environments
- Amp, GPT-5.4 oracle: https://ampcode.com/news/gpt-5.4-the-new-oracle
- Amp workspaces: https://ampcode.com/docs/collaborate/workspaces
- Copilot BYOK (third-party): https://startdebugging.net/2026/04/github-copilot-vs-code-byok-anthropic-ollama-foundry-local/
- Aider polyglot leaderboard via Simon Willison: https://simonwillison.net/2025/Feb/25/aider-polyglot-leaderboard/
- PEAR planner-executor benchmark: https://arxiv.org/pdf/2510.07505
- Debate helps weak judges: https://arxiv.org/pdf/2605.27483
- Sycophancy in code assessment: https://arxiv.org/pdf/2607.10411
- Local models for coding (martinfowler.com): https://martinfowler.com/articles/exploring-gen-ai/local-models-for-coding-experiences.html
- Cedar authorization: https://docs.cedarpolicy.com/auth/authorization.html
- git-config(1): https://man.cx/git-config
- Terraform health assessments: https://developer.hashicorp.com/terraform/enterprise/v202502-2/workspaces/health
- CEL admission policies (secondary): https://oneuptime.com/blog/post/2026-02-09-cel-admission-policies-replace-webhooks/view
- llama.cpp server slots (secondary): https://dev.to/multigrid/serving-parallel-requests-with-llamacpps-server-slots-c90
- llama.cpp issue #15008: https://github.com/ggml-org/llama.cpp/issues/15008
- llama.cpp PR #22851: https://app.semanticdiff.com/gh/ggerganov/llama.cpp/pull/22851/overview
- vLLM scheduler config: https://docs.vllm.ai/en/v0.10.2/api/vllm/config/scheduler.html
- LiteLLM scheduler: https://docs.litellm.ai/docs/scheduler
- Kubernetes pod priority and preemption [unverified this session]: https://kubernetes.io/docs/concepts/scheduling-eviction/pod-priority-preemption/
- Inference engine benchmark (indicative): https://computingforgeeks.com/ollama-vs-vllm-vs-llama-cpp/
- OTel GenAI conventions explained (secondary): https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained
- OTel GenAI 2026 status (secondary): https://dev.to/azena-ai/opentelemetrys-genai-semantic-conventions-are-not-stable-yet-heres-what-actually-shipped-in-2026-3mke
- Langfuse OpenTelemetry: https://langfuse.com/integrations/native/opentelemetry.md
- Agent commit attribution: https://agentpatterns.ai/workflows/agent-commit-attribution/

# "The Lab" inside Vigil: assessment of the ChatGPT research-lab proposal (2026-11-01)

**Status.** Advisor assessment for the owner. Input: the ChatGPT report "A Frontier-Focused Path From Vibe Coder to AI Engineer, Agent Researcher, and Software Factory Engineer" (owner-supplied, unverified citations), read against `docs/plans/phase-3.md` v2, the kickoff, and the seven research reports. Unverified source per ADR-0006. Not a code review: the attached archive held the phase-3 documents, not the repository.

**Bottom line.** The project is sound and it belongs in Vigil — but not as a new system. About three quarters of "The Lab" already exists in the phase-3 plan under other names (replay eval, public-PR task pool, scoreboard, yardstick, experiments #13–#24, the self-edit job, `correct`, the planned `/learn` page). The Lab is the right **name and front door** for that machinery: Vigil's Track C made first-class. Build it as the `/learn` page plus an `experiments` entity plus a research-note discipline, at G4–G5, after the throughput gate; do the paper part (a ruling, a note template, backfilling experiments #13–#24) now. Do not write it in Rust; let it **study** Rust as its first non-Python subject (p3-63). Vigil can build most of it as Vigil jobs.

## 1. What the proposal is, in Vigil's terms

The ChatGPT report proposes an "autonomous AI engineering research factory": question → orchestrator → agents in isolated environments → verification harness → experiment database → judge + statistics → keep/reject → report or PR; plus a home benchmark ("VigilBench", 30–100 tasks mined from Vigil and ParkAgent history), a seven-study research programme, and a 16-week personal curriculum (tiny transformer → local inference → from-scratch harness → sandbox → traces → benchmark → verifier → repo map → memory → parallel workers → router → experiment controller → study → paper).

Mapped onto the plan of record:

| Lab component (ChatGPT) | Already in Vigil | Gap |
|---|---|---|
| Isolated worktree / container per run | session containers, no-egress, single-commit checkouts, gateway-only keys | none |
| Verification harness | the verifier (fresh checkout, hidden tests, base/before/after), `verify/` plug-ins p3-54 | none |
| Experiment database (traces, cost, tokens, score, git) | `events`, scoreboard p3-19, Phoenix traces, packet telemetry p3-50, `requested_model`/`served_model` p3-49 | no first-class **experiment** row tying arms, slice, k, pins and verdict together |
| Judge + statistics | yardstick p3-37 (Wilson bounds, ≥50 outcomes, k≥3), paired McNemar/Wilcoxon (#17 design), SPRT p3-31; ruling: **no LLM judge** | a reusable stats/report step; today each experiment's verdict is written ad hoc |
| VigilBench from own history | p3-12 public-PR task pool (≥200 tasks), #17's "60–100 replayable tasks from merged history", p3-24 hidden-test admission + hackability audit, pre-screen 0/3 and 3/3 | Vigil's version is stricter (admission gate, leak audit, 20 reruns); ChatGPT's lacks them |
| Study 1: verification ablation | implicit in the thesis; verifier arms not yet an experiment | new experiment entry |
| Study 2: context / repo maps | experiment #17 (arms A/B/C, codemap) | none |
| Study 3: agent memory | experiment #22 (layer-5 lessons in/out), R6/#13 fresh vs fork | none |
| Study 4: model routing | #19 cheap-first cascade, #21 tower economics, p3-36–40 | none |
| Study 5: single strong agent vs multi-agent | not registered | new experiment entry (chains p3-27 give the arm) |
| Study 6: architecture for agents | R19 PROMOTE rule, p3-62 `correct`, p3-53 characterization-first | measured only indirectly |
| Study 7: self-improving harness ("autoresearch loop") | E4 / p3-34 self-edit job with held-out delta; p3-62 proposes, never applies | none — and Vigil's version is safer (below) |
| Research report per study | experiments README entries; verdicts scattered | a fixed note template |
| Dashboard | `/learn` is already in R3's page list as "planned" | the page itself |
| From-scratch coding harness | out of scope (R1: harnesses run keyless in-container; ADR-0006 thinning) | learning exercise, possibly a control arm later |
| Tiny transformer / nanochat / Track A model research | out of scope; the tower cannot tune its own model (74 GB LoRA; E9 retargeted to 8–9B; ≥300 traces months away) | personal curriculum, not a Vigil track |

Reading: the ChatGPT report independently re-derives Vigil's Track C and the experiments register from Karpathy, Anthropic, OpenAI, Tan, Factory and Warp. That is confirmation, not a new direction. Its one structural contribution is to give that machinery a single identity and a publishing discipline.

## 2. Where the proposal is wrong for Vigil

1. **"Keep → git commit."** Karpathy's `autoresearch` can self-commit because its metric (validation bits-per-byte on a fixed budget) is not gameable by the agent. A harness change scored on a self-built benchmark is: 63% of a frontier model's SWE-bench Pro "solves" were retrieved (9% from bundled `.git`), and an abort option moved reward hacking 54%→9% (factory research, findings 1 and 4). Vigil already rules this: the self-edit job proposes a PR with a held-out delta, `correct` emits cards, and nothing a worker touches decides landing. **The Lab's loop ends in a card or a draft PR, never a commit.** The ChatGPT diagram's "keep change → git commit" must not be adopted.
2. **LLM judge in the loop.** The diagram's "Judge + Statistics" box is fine if the judge is the verifier and the statistics are the yardstick; an LLM grader is on Vigil's not-adopted list and stays there. Warp's transcript-read scorers may be telemetry (V8), never a verdict.
3. **A seventh harness.** Building "your own minimal coding agent" is good pedagogy and a bad product item: R1 admits only harnesses that run keyless in-container; ADR-0006 forbids thickening. If it is ever in the repo, it is a **control arm** (a 6-tool harness with a ~1k-token startup prompt against OpenCode's ~7k and Claude Code's ~33k), after p3-23 factory configs exist, with its own replay slice. Not before G4.
4. **Track A (model research) on the tower.** The report's "fork nanochat, let an agent experiment with architecture" is a personal curriculum item. Vigil's own research says the tower cannot fine-tune Qwen3.6-35B, E9 needs ≥300 clean local traces that do not exist, and a trained model enters Vigil only through the held-out eval in `evals/run.py`. Keep nanochat out of the repo; keep E9 as the one model-training experiment Vigil owns.
5. **Two GPUs as two independent workers.** Plausible for ≤14B models; Qwen3.6-35B-A3B at Q4 is ~20 GB of weights and already spans both 16 GB cards. The "GPU 0 worker / GPU 1 judge" layout needs a smaller second model and a measured throughput comparison, which is itself an experiment (#21's domain), not a given.
6. **The timeline.** A 16-week plan starting now spends the same owner attention and the same $200/month that the throughput gate (30 product PRs through the full gate) needs. The plan's order already says "C's replay eval is the dependency for every A/B", and places it at G5. The report's incentive is breadth of learning; Vigil's one metric is owner-minutes per merged product PR. The kill criterion exists because of exactly this pull.

Note the symmetry in the kill criterion: if Vigil misses the throughput gate, "Vigil is replanned as an eval and training asset" — which is The Lab. The Lab is therefore either Vigil's phase 7 or Vigil's plan B. In both cases it is inside Vigil. Building it beside Vigil would duplicate the verifier, the sandbox, the scoreboard and the budgets, and would violate the one lesson every source in the report shares: go deep before going parallel.

## 3. What The Lab is, if adopted (proposal for ruling R27)

**The Lab** is the name for Vigil's measurement surface: `/learn` (route per R3), `evals/`, `docs/experiments/`, `docs/research/`. It consists of:

- **An `experiment` entity** (`ex-` prefix, ADR-0008 style): id, question, hypothesis, metric (from the scoreboard's host-side scorers only), slice `(repo, shape, size)`, arms (each a factory config revision + preset + prompt revision + harness pin + dev-image digest), task set (frozen replay pool revision, admitted tasks only), k, budget line, pins, `state {proposed → approved → running → analysed → verdict | aborted}`, verdict `{adopt, reject, inconclusive}`, and **the rule it would change** (a routing graduation, a cap, a packet layer, a ladder promotion, a `review.yaml` class). An experiment with no rule it could change is refused at proposal. Experiments are proposed as brief cards (advisor scope, p3-04), approved in the Inbox, run under their own budget line, and end in a card or a draft PR.
- **A runner** that composes shipped pieces: replay pool → factory configs as arms → verifier verdicts → scoreboard rows → yardstick statistics → note. No new sandbox, verifier, or metering.
- **A research note per experiment** (template under `docs/experiments/`): question, hypothesis, configuration, frozen revisions and pins, task set and admission audit, raw trajectory pointers, grader, results with uncertainty, failure taxonomy, limitations, reproduction command, and the rule changed or left unchanged. Experiments #13–#24 are backfilled into the template now (docs tier).
- **`/learn`**: the register, each experiment's arms and running totals, the Pareto view per (model, harness, template) it already shares with `/factories`, and the notes.

What it never does: merge, promote a rung (SPRT does that, p3-31), grade with a model, run on a task set that has not passed admission (p3-24), or read client-repo data when `training_allowed` is false (R20).

## 4. Timing: gates, not dates

| When | Lab work | Why |
|---|---|---|
| Now (G0–G1, paper) | Ruling R27 line; `docs/experiments/TEMPLATE.md`; backfill #13–#24 into it; feature rows `learn`, `experiments`, `lab-runner` with status `planned` | zero code; one PR of the docs tier; makes every later verdict comparable |
| G2 | p3-50 packet telemetry and p3-19 scoreboard as planned — these *are* the Lab's instrumentation; the plan already calls p3-50 the cheapest item | no new work, only the realisation that they serve two purposes |
| G3 | experiment #21 (tower economics) runs **as the first Lab experiment** using the template, by hand if the runner does not exist; its note is the Lab's first artefact | #21 is already scheduled at G3 and decides a kill criterion |
| G4 | `experiments` table (schema lease, pinned), runner (code tier, Vigil job), `/learn` v0 (Vigil job); experiments #19, #17, #22 and the new verification-ablation and single-vs-multi entries run through it; p3-12 task pool is the dataset | p3-23 factory configs give arms an identity; p3-12 gives tasks; the yardstick gives statistics |
| G5 | the self-edit job (p3-34) and `correct` (p3-62) become Lab experiment proposers; replay eval weekly k≥3 is the Lab's standing run | this is the "autoresearch loop", with a card where Karpathy has a commit |

Calendar translation, with the caveat that the plan refuses dates for good reasons: G0–G3 is the next several weeks of work at the pace phase 2 set (19 migrations in ten days, but G1's exit is ten consecutive clean landings and G3's is 30 product PRs). That puts the Lab's code at G4, most plausibly **January–February 2027**, with the paper part done in **November–December 2026**. Starting the code in December would mean starting it before the gate that justifies it; the owner-minutes metric would pay for it twice.

## 5. Rust

Per R26 and `rust-and-retrieval.md`: vigild stays Python; Rust enters per component when a profiled trigger fires. The Lab's components are an orchestration policy (I/O-bound, SDK-churned), SQLite rows, scipy statistics and a web page — no trigger fires. Writing The Lab in Rust would be the "slowest SDK" tax the report documents, for a component whose latency is model calls and test runs.

Where Rust belongs in The Lab:

1. **As subject.** p3-63's Rust target stack gives the richest outside oracle Vigil will have (rustc, clippy, nextest JUnit, cargo-deny, sampled cargo-mutants, proptest, miri). The verification-ablation study (read+edit → +shell → +tests → +full `verify/`) is most informative where the full-verification arm has the most signal, which is Rust. **Recommendation: the Lab's first non-Vigil-history experiment runs on the Rust template repos.** Model Rust skill is benchmark-dependent (5–86% across 2026 sets), so the Lab is also where Vigil's own Rust numbers come from, which p3-63 already requires ("only Vigil's numbers count").
2. **One defensible Rust crate, if the owner wants hands-on Rust inside the repo:** `vigil-lab-stats`, a CLI that reads the scoreboard export (CSV or SQLite) and emits the note's statistics section (Wilson bounds, paired McNemar, Wilcoxon, SPRT trace, per-stratum tables). Stable inputs, no LLM SDK, correctness is the whole point, proptest fits, and it is the one Lab component that is pure. It is optional; the Python default is a few scipy calls. Per R26 it should sit behind a JSON interface so either implementation serves.
3. **Per the §18 triggers later:** `vigil-hook` (first non-Python target stack) and the tantivy code map (if #17 adopts a map and latency targets fail). Both are Vigil items, not Lab items.

## 6. Can Vigil build The Lab?

Mostly yes, by the plan's own tiering:

| Piece | Tier | Builder |
|---|---|---|
| R27 ruling line, note template, backfill of #13–#24, feature rows | docs / pinned (rulings) | owner reads; drafting is a docs-tier PR |
| `experiments` table and migration step | pinned (schema lease) | owner-read draft |
| runner (`vigild/learning/lab.py` composing replay, configs, scoreboard, yardstick) | code | Vigil job from a contract, after p3-23 and p3-12 |
| `/learn` page | code | Vigil job (same pattern as the E10 console pages) |
| note generator | code | Vigil job |
| experiment entries that change verifier arms (verification ablation) | pinned (verifier) | owner-read draft |
| the experiments themselves | Lab runs | the runner, under their own budget line |

Two cautions. Lab PRs on the Vigil repo are Vigil PRs, not product PRs; they must not be counted toward the throughput gate or be allowed to crowd out ParkAgent traffic (R10 unblocks that first). And the Lab's own experiments have the worker-grades-itself problem one level up: an experiment proposed by the self-edit job and scored by the Lab must still run on tasks admitted by p3-24 and end in a card. The rule that survives everything applies to the Lab as it applies to a worker.

## 7. What to take from the report regardless

- The **note template** fields (question, hypothesis, configuration, frozen revision, model/harness version, task dataset, raw trajectories, grader, results, uncertainty, failures, limitations, reproduction). Adopt verbatim as `docs/experiments/TEMPLATE.md`.
- **Task horizon as a stratum** (METR): tag replay tasks by how long they take the owner unaided; ask whether a change moves the solve rate on longer tasks. Cheap to add to `metadata.json` in p3-12.
- **Record more than pass/fail**: completion, wall-clock, model calls, tokens, cost, tool calls, changed lines, test executions, context size, retries, human intervention. The scoreboard already has most; `human_intervention` and `changed_lines` should be explicit columns.
- **Two new experiment entries:** verification ablation (four arms) and single strong agent vs chain (p3-27 gives the multi-agent arm, cap 3).
- The curriculum itself (nanochat, a from-scratch harness, vLLM) is the owner's learning path. It is valuable and it is outside the repo.

## 8. Don't adopt

Self-committing experiment loops; an LLM judge; a home-grown harness as a worker; nanochat or any model-training code in the Vigil repo before E9's trace threshold; a separate "forge/" repository duplicating sandbox, verifier and metering; a 16-week calendar; writing the orchestration in Rust; GPU-split assumptions without #21's measurement.

## 9. Proposed ruling text (for `docs/owner-rulings.md`, Product decisions)

> **R27 The Lab** (2026-11-0x): The Lab is Vigil's measurement surface: `/learn`, `evals/`, `docs/experiments/`, `docs/research/`. An experiment is a first-class row (question, hypothesis, metric from host-side scorers, slice, arms as factory-config revisions, frozen admitted task set, k, budget line, pins, verdict, and the rule it would change); experiments are proposed as brief cards, approved in the Inbox, and end in a card or a draft PR, never a merge or a rung change. No LLM judge. Paper now (template, backfill #13–#24); table, runner and page at G4; proposers (self-edit, `correct`) at G5. Vigild stays Python for it; Rust is the Lab's first non-Python subject via p3-63; an optional pure stats CLI may be Rust behind a JSON interface. Model-training curricula stay outside the repo.

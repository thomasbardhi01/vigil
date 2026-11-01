# Research reports (unverified sources)

The reports behind the phase-3 plan (`docs/plans/phase-3.md`, §14; ruling R11).
Each was produced by a research task for the owner and is committed as the
owner supplied it.

**Every report here is an unverified source** (ADR-0006: no citation from
research notes enters `docs/sources.md` until it has been fetched and checked;
until then a claim is marked "per research note, unverified"). Figures,
quotes, product states and dates are as the report found them, often vendor
self-reports; several items are marked unverified inside the reports
themselves. Cite a report as "per `docs/research/<file>`, unverified".

Packet assembly reads no file under `docs/research/`: no layer of a worker,
reviewer, auditor or coord packet includes them
(`tests/packets/test_packets.py::test_research_reports_reach_no_packet_layer`).

| File | Original title | Cut-off | Feeds |
|---|---|---|---|
| `factory-research-oct-2026.md` | Evidence confirms Vigil's gates, redirects its retries | 2026-10-29 | R1–R8, E1–E11, N1–N3 |
| `amp-and-warp-philosophy.md` | Vigil keeps the gate, drops the ceremony | 2026-10-29 | V1–V8; the design philosophy section; don't-adopts |
| `verification-bottleneck.md` | Review saturates first; Vigil's verifier is the lever | 2026-10-30 | p3-06, p3-08, p3-21; experiments #18–#22 |
| `command-center-landscape.md` | Build the gate's cockpit, not another dashboard | 2026-10-30 | §8 (cockpit), §11 (data model); its phase numbers are superseded by the plan's gates |
| `model-auto-routing.md` | Route on verifier outcomes, not on prompts | 2026-10-30 | §10, R13, p3-36–p3-40, p3-49 |
| `landing-and-trust-ladder.md` | Conflict-free landing, Lauren Tan's trust ladder, the one-app question, and Vigil as a service | 2026-10-31 | §7, R15–R21, p3-09, p3-05, p3-47, p3-48 |
| `rust-and-retrieval.md` | Vigil and Rust: code-retrieval evidence, Rust AI infrastructure, and a Rust target stack | 2026-11-01 | R26, p3-63, experiment #17's design |
| `the-lab-assessment.md` | "The Lab" inside Vigil: assessment of the ChatGPT research-lab proposal | 2026-11-01 | R27, p3-64–p3-68, experiments #25–#26 (an advisor assessment of an owner-supplied report with unverified citations) |

Paths inside the reports (`/home/claude/reports/…`, `/home/claude/vigil/…`)
are the research environment's, not this repo's; the report each one names is
the file above with that title.

## Claims under test

The claims register (p3-69). The claim text is the owner's.

| # | Claim | Falsified if | Vigil item that measures it |
|---|---|---|---|
| C1 | One person with a gate lands verified software faster per owner-minute than the same person with the best free pipeline | the strawman baseline (§3, brief B) matches Vigil on owner-min/PR and 30-day revert rate | p3-41, experiment #20 + new #27 |
| C2 | Hidden tests in a fresh checkout catch defects that visible tests and review miss, at a cost worth paying | post-merge revert and CI-at-48h rates do not differ between hidden-test and visible-test arms on Vigil's repos | p3-44 + new #28 |
| C3 | Autonomy earned per shape by SPRT is safer and cheaper than uniform human review | ladder promotions do not reduce owner-minutes, or promoted shapes revert more than rung-0 shapes | p3-31 + new #29 |
| C4 | The gate transfers: it holds on repos, stacks and machines that are not the owner's | the first non-owner repo at `mvp` profile needs a gate property removed to land anything | R21, p3-63, Track F |
| C5 | Vigil's verified, cost-labelled trajectories are an asset in their own right | no buyer, no benchmark and no training recipe wants real-repo traces with provenance beyond what SWE-Gym-class synthetic sets already give | R20, E9, p3-14 |

## Research briefs

Each brief's report lands as `docs/research/<brief-id>-<slug>.md`, under the
unverified notice above.

| Brief | Subject | Status | Tier | Would change |
|---|---|---|---|---|
| A | The claim and the counterfactual | planned | 2 | the `docs/design.md` thesis paragraph and the G3 brand card |
| B | The cheap strawman | planned | 1 | #20 (new arm #27) and C1's wording; rewrites the `docs/design.md` thesis if the strawman has ≥4 of 5 gate properties |
| C | Prior art per gate property | planned | 2 | this README's prior-art section and the claim wording; anything found to be standard leaves the "edge" list |
| D | Falsifiers | planned | 2 | entries #28–#31 and the kill criteria, one line per property |
| E | The numbers nobody has | planned | 1 | the order of the Lab's first five experiments and the n_required field; drops any closed gap, citing the paper that closed it |
| F | The asset thesis | planned | 1 | p3-12/p3-24 priority, the trajectory exporter schema, and plan B's wording in the kill criterion |
| G | Transfer | planned | 2 | R21's mvp row, Track F's `vigil init`, and the first non-owner repo's acceptance criteria |
| H | The abstract | planned (owner work, not assigned) | 3 | — |

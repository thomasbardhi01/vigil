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

Paths inside the reports (`/home/claude/reports/…`, `/home/claude/vigil/…`)
are the research environment's, not this repo's; the report each one names is
the file above with that title.

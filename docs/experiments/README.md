# Experiments

One numbered entry per experiment. Earlier experiments are numbered in `docs/learning/README.md` and the issues; this directory starts at #12.

Each experiment runs:
- only after the bench freeze lifts;
- only through vigild;
- after the owner confirms it;
- on the experiment budget line.

Its results and decision are committed here once it has run.

From #13 on, each experiment has a note in `TEMPLATE.md` form (`NN-<slug>.md`, ruling R27); a field nobody recorded says `unknown`.

| # | Experiment | Question | Data | Measure | Status |
|---|---|---|---|---|---|
| 12 | omp's edit benchmark against tower-qwen (ADR-0006 H; omp research C14) | How often does the tower's model fail an edit, and does a harness lift it? | omp's typescript-edit-benchmark, run by us | edit success rate, harness off vs on | planned (after the freeze). omp's published figures are not cited (per research note, unverified). |
| 13 | Retry policy (ADR-0006 H) | Does a retry do better from a full-context fork, or from a flush plus the verifier's failure category? | 30 retries on vigil's own tasks or Smoke, never ParkAgent | hidden-test pass rate, cost per retry | planned (after the freeze). #84 already chose flush below attempt 3; this measures that choice. |
| 14 | Grok Build harness spike (p3-11; R1) | Does Grok Build run keyless in the egress-locked session image against the gateway, with no xAI sign-in? | one S task on `thomasbardhi01/vigil`; smokescreen logs | hosts it tries to reach; whether its output carries token counts; keyless yes/no | planned (G4). Pass makes it a harness candidate; fail keeps it a preset behind the gateway only. |
| 15 | Factory Droid harness spike (p3-11; R1) | Does `droid exec` with BYOK run with no Factory login and no phone-home? | as #14 | as #14 | planned (G4). A Factory login is reported required even with BYOK (per research note, unverified), so the expected verdict is out. |
| 16 | Ask-gate on or off (p3-26) | Does the ask-gate (`contract_gate`) improve outcomes when on? | unknown | unknown | planned. Rule: `contract_gate`'s default in `configs/routing.yaml`. |
| 17 | Code map in or out (p3-33; R26) | Does a structural code map raise the verified pass rate or lower $/solved? | replay pool, pre-screened, k=3, tower and one Claude model | pass rate, $/solved (McNemar, Wilcoxon) | planned (G5). Design in `17-code-map-in-or-out.md`. |
| 18 | Reserved | The plan of record lists #18 among the phase-3 entries but defines no question for it. | — | — | open: the owner names it. |
| 19 | Cheap-first cascade (p3-40; §10) | On rule-9 S tasks on one public repo, does trying the cheapest allowed preset first and escalating on the verifier's failure beat the rule's default on $/solved at equal pass rate? | replay pool; ≥9 runs per arm | verifier pass rate (Wilson interval), gateway $/solved, cascade pass rate | planned (G4, before any bounded decide). A win makes `cascade: [tower-qwen, claude-sonnet]` the rule for that slice. |
| 20 | By-hand baseline (p3-41) | What does a comparable change cost the owner by hand, and with Strawman v1 (#27)? | ≥10 comparable tasks, entered by the owner | $ and owner-minutes per task, recorded identically for both baselines | planned (G2). Feeds `baseline_usd` and `baseline_min` in the kpis route; the kill criterion compares against it at 30 product PRs. |
| 21 | Tower economics (p3-45) | Is the tower cheaper per solved task than Sonnet? | 20 S tasks × 3 runs, tower vs Sonnet | $/solved, the tower at measured watt-hours | planned (G3). If the tower's $/solved exceeds Sonnet's, rule 6 flips to Sonnet by default and the tower serves the decider, hidden-test writing and replay (kill criterion). |
| 22 | Layer-5 lessons in or out (p3-33) | Do layer-5 lessons in the packet raise the verifier pass rate? | replay pool, k≥3 | hidden-test pass rate, $/solved | planned (G5). |
| 23 | Codex CLI keyless (R9) | Does the Codex CLI run keyless against the gateway? | unknown | keyless yes/no | planned (when an OpenAI API key exists). |
| 24 | claude-sub spike (p3-60; R24) | Can Claude Code run in-container on the owner's subscription through a token only the gateway holds? | one S job | token never in the container; $0.00 API spend; window delta | planned (G2, pinned). |
| 25 | Verification ablation (R27) | How much does each verification capability add? | Vigil's history, then the p3-63 Rust templates | verifier pass rate, $/solved per arm (read+edit / +shell / +tests / +full `verify/`) | proposed. Rule: the verifier plug-ins each readiness profile requires per shape (R21), and lite-lane eligibility (R14). |
| 26 | Single strong agent vs chain (R27; p3-27) | Does one strong agent beat a chain of at most three links? | unknown | verifier pass rate, $/solved per arm | proposed. Rule: when coord splits work into a chain, and the chain cap (p3-27, 3). |
| 27 | Strawman v1 arm for #20 (claim C1) | Does the cheap strawman match Vigil on owner-min/PR and 30-day revert rate? | placeholder until Brief B | owner-min/PR, 30-day revert rate | proposed. Could change: the kill criteria and the `docs/design.md` thesis. |
| 28 | Hidden vs visible tests on post-merge reverts (claim C2; p3-44) | Do post-merge revert and CI-at-48h rates differ between hidden-test and visible-test arms? | Vigil's repos | revert rate, CI at 48 h | proposed. Could change: R14 and whether hidden tests stay on by default. |
| 29 | Ladder vs flat review (claim C3; p3-31) | Is autonomy earned per shape safer and cheaper than uniform human review? | unknown | owner-minutes, revert rate by rung | proposed. Could change: R4 and the ladder ADR. |
| 30 | Spend-cap tail (claim C1, cost side) | How does the hard per-task spend stop behave in the tail? | gateway metering | unknown | proposed (may run at G2). Could change: R23 and the per-task caps (p3-56). |
| 31 | Ladder calibration (claim C3; p3-31, p3-44) | Do promoted shapes revert more than rung-0 shapes? | unknown | revert rate of promoted shapes | proposed. Could change: R4 and the SPRT thresholds (p0, p1). |

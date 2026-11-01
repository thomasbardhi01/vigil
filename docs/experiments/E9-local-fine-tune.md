# Experiment E9: Local fine-tune (8–9B student on verified local traces)

- **Status:** planned (G5; ADR-0007, amended 2026-11-01)
- **Item / ruling:** ADR-0007; p3-35
- **Budget line:** unknown
- **Claim tested:** C5
- **n_required:** 

## Question

Does QLoRA SFT of an 8–9B student on verified local traces beat the cost-normalised bar?

## Hypothesis

Single-digit gains at most at ≤300 own-model traces (published few-hundred-trace wins are teacher-to-weak-base); pre-registered before E3.

## Configuration

E0 smoke (30 tasks, n=1; k=3 repeats on 10); E1 best-of-n baseline (n=8, deployment-legal selection, pass@1/2/4/8, Best@8, pass^3 from the same samples); E2 train collection to ≥300 verified, audit-clean local traces; E3 learning curve: QLoRA on 100/200/300-trace subsets × 3 seeds; E4 held-out bar. A `public-open` arm (Nemotron-SFT-SWE-v2, Nebius), if run, is a separate ablation, never mixed into `local` (ADR-0007 amendments a, d, f).

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

Pre-registered before any run (ADR-0007 amendment d): temperature, seeds per (task, sample index), the quant and the llama.cpp build hash for a tower arm. Student and teacher model digests: unknown until E0.

## Task set and admission audit

Eval split ≥100 tasks, repos and tasks never in the train collection (amendment c). Train collection: verified-pass only, ≤3 traces per task, de-duplicated, edit-without-test dropped, Opus hackability audit on every kept trace; provenance on loss-bearing tokens, train-split cards human- or local-authored (amendments e, g).

## Raw trajectory pointers

unknown

## Grader

The verifier's hidden tests in the no-history checkout; paired McNemar at p < 0.05 (ADR-0007 part 4).

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

unknown

## Reproduction command

unknown

## Rule changed or left unchanged

The local model is replaced only if the student beats both the 35B's Best@8 at matched tower-hours and the 35B's pass@1 (amendment b), and ADR-0007 part 4's bar; otherwise the current model stays and the ≥300-trace gate stays a trigger, not a promise.

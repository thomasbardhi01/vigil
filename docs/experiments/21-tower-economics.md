# Experiment #21: Tower economics

- **Status:** planned (G3; the first Lab experiment, run by hand with this template if the runner doesn't exist yet)
- **Item / ruling:** p3-45
- **Budget line:** unknown

## Question

Is the tower cheaper per solved task than Sonnet?

## Hypothesis

unknown

## Configuration

Two arms: tower-qwen and Sonnet. The tower arm is also reported as Best@8 by deployment-legal selection (worker-visible tests, reviewer, optional critic; hidden tests score, never select), with pass@1/2/4/8 and pass^3 from the same samples, at matched tower-hours (ADR-0007 amendments b, d).

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

Pre-registered before any run (ADR-0007 amendment d): temperature, seeds per (task, sample index), the quant and the llama.cpp build hash for a tower arm. Other pins unknown.

## Task set and admission audit

20 S tasks × 3 runs.

## Raw trajectory pointers

unknown

## Grader

Verifier pass rate; $/solved, the tower at measured watt-hours.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

20 tasks cannot power a paired McNemar test; the decision-grade eval split is ≥100 tasks (ADR-0007 amendment c). Vendor scores for Qwen3.6-35B-A3B (73.4% Verified, Alibaba's scaffold) are never the comparison; only Vigil's own runs count.

## Reproduction command

unknown

## Rule changed or left unchanged

If the tower's $/solved exceeds Sonnet's, rule 6 flips to Sonnet by default and the tower serves the decider, hidden-test writing and replay (kill criterion).

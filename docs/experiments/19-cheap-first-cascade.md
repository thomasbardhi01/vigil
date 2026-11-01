# Experiment #19: Cheap-first cascade

- **Status:** planned (G4, before any bounded decide)
- **Item / ruling:** p3-40; §10
- **Budget line:** unknown

## Question

On rule-9 S tasks on one public repo, does trying the cheapest allowed preset first and escalating on the verifier's failure beat the rule's default on $/solved at equal pass rate?

## Hypothesis

unknown

## Configuration

Cheapest allowed preset first with `escalate_attempt: 2`; escalation on the verifier's failure as a new attempt.

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown

## Task set and admission audit

Replay pool; ≥9 runs per arm.

## Raw trajectory pointers

unknown

## Grader

Verifier pass rate with a Wilson interval; gateway $/solved; the cascade's pass rate.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

unknown

## Reproduction command

unknown

## Rule changed or left unchanged

A win makes `cascade: [tower-qwen, claude-sonnet]` the rule for that slice (`configs/routing.yaml`).

# Experiment #18: Routing yardstick: Jev proposer vs rules, per slice

- **Status:** planned (G4, p3-37)
- **Item / ruling:** p3-37; R13
- **Budget line:** unknown

## Question

Per slice (repo, shape, size), does the Jev proposer choosing inside the rules' permitted set beat the rules' own choice?

## Hypothesis

unknown

## Configuration

Arms per slice: the rule's choice; the proposer's choice inside `allowed_presets(task)` (§10, R13). One model per attempt; escalation is a new attempt.

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown

## Task set and admission audit

A frozen replay set of ≥20 tasks per slice, each arm run ≥3×; ≥50 verifier outcomes per arm, no task counting more than 3.

## Raw trajectory pointers

unknown

## Grader

Verifier outcomes. Gates (all required): the cheap arm's lower 95% Wilson bound exceeds metered cost_cheap/cost_strong by ≥10 points (tower floor 0.5); the cascade's pass rate is within noise of the strong arm; Jev calibration ≥0.80 on ≥50 shadow answers at the 0.85 threshold; any model, served-model, price, harness-pin or dev-image change demotes, with a re-run at 30 days.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

unknown

## Reproduction command

unknown

## Rule changed or left unchanged

Whether a slice graduates to bounded decide (p3-38: a `graduated` entry in `configs/routing.yaml`, each an owner-merged PR), or stays rules-only.

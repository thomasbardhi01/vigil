# Experiment #28: Hidden vs visible tests on post-merge reverts

- **Status:** proposed (claims register, p3-69)
- **Item / ruling:** depends on p3-44
- **Budget line:** unknown
- **Claim tested:** C2
- **n_required:** 

## Question

Among PRs that the visible tests alone would have passed, do the ones where hidden tests changed the outcome differ in post-merge reverts?

## Hypothesis

unknown

## Configuration

Counterfactual, the primary design: every PR goes through the full gate; per PR, record whether hidden tests changed the outcome (failed a draft the visible tests passed, or forced a fix), and compare reverts among PRs the visible tests alone would have passed. No visible-only arm ships code. Brief D evaluates the design.

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown

## Task set and admission audit

unknown

## Raw trajectory pointers

unknown

## Grader

Post-merge revert rate and CI-at-48h rate (p3-44).

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

unknown

## Reproduction command

unknown

## Rule changed or left unchanged

Could change: R14 (the lite lane skips hidden tests) and whether hidden tests stay on by default.

# Experiment #20: By-hand baseline

- **Status:** planned (G2)
- **Item / ruling:** p3-41
- **Budget line:** unknown

## Question

What does a comparable change cost the owner done by hand in Claude Projects?

## Hypothesis

unknown

## Configuration

Two baselines: the by-hand owner workflow AND Strawman v1 (experiment #27), with owner-minutes recorded identically for both. Owner-minutes come from one instrument in both arms: a per-task start/stop timer the owner runs. Tasks are matched but different, paired by shape and size, alternating which arm goes first.

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown

## Task set and admission audit

≥10 comparable tasks, entered by the owner.

## Raw trajectory pointers

unknown

## Grader

$ and owner-minutes per task, owner-entered.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

unknown

## Reproduction command

unknown

## Rule changed or left unchanged

Feeds `baseline_usd` and `baseline_min` in the kpis route; the kill criterion compares against it at 30 product PRs.

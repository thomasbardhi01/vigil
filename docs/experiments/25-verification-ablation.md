# Experiment #25: Verification ablation

- **Status:** proposed (the Lab brief, 2026-11-01)
- **Item / ruling:** R27
- **Budget line:** unknown

## Question

How much does each verification capability a worker has add to the verified pass rate and $/solved?

## Hypothesis

unknown

## Configuration

Four arms: read+edit; +shell; +tests; +the full `verify/` CLI.

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown

## Task set and admission audit

First on Vigil's own history, then on the p3-63 Rust templates.

## Raw trajectory pointers

unknown

## Grader

Verifier pass rate and gateway $/solved per arm.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

unknown

## Reproduction command

unknown

## Rule changed or left unchanged

The verifier plug-ins each readiness profile requires per shape (R21), and lite-lane eligibility (R14).

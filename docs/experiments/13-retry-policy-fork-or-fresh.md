# Experiment #13: Retry policy: fork or fresh

- **Status:** planned (after the freeze)
- **Item / ruling:** ADR-0006 H; R6
- **Budget line:** unknown

## Question

Does a retry do better from a full-context fork, or from a flush plus the verifier's failure category?

## Hypothesis

unknown

## Configuration

Two arms: `fork` (resume the failed attempt's transcript) and `fresh` (new context with the prior diff and the verifier's category feedback; the current default, ADR-0005).

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

Pre-registered before any run (ADR-0007 amendment d): temperature, seeds per (task, sample index), the quant and the llama.cpp build hash for a tower arm. Other pins unknown.

## Task set and admission audit

30 retries on vigil's own tasks or Smoke, never ParkAgent. Admission audit: unknown.

## Raw trajectory pointers

unknown

## Grader

Hidden-test pass rate from the verifier; cost per retry from gateway metering.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

A retry arm on the tower is scored by hidden tests only; nothing selects by them (ADR-0007 amendment d). A difference is credited only above the run-to-run spread of k ≥ 3 repeats.

## Reproduction command

unknown

## Rule changed or left unchanged

R6 (retry context is fresh) stands or flips to fork; #84 already chose flush below attempt 3.

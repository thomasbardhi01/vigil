# Experiment #14: Grok Build harness spike

- **Status:** planned (G4, p3-11)
- **Item / ruling:** p3-11; R1
- **Budget line:** unknown

## Question

Does Grok Build run keyless in the egress-locked session image against the gateway, with no xAI sign-in?

## Hypothesis

unknown

## Configuration

Grok Build CLI in the session image, pointed at the gateway; smokescreen logging every host it tries.

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown

## Task set and admission audit

One S task on `thomasbardhi01/vigil`.

## Raw trajectory pointers

unknown

## Grader

Smokescreen logs (hosts reached), whether its output carries token counts, keyless yes/no.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

unknown

## Reproduction command

unknown

## Rule changed or left unchanged

R1: pass makes Grok Build a harness candidate; fail keeps it a preset behind the gateway only.

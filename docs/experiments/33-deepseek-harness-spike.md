# Experiment #33: DeepSeek Harness (dsh) spike

- **Status:** planned (G4, after p3-23; the same shape as #14 and #15)
- **Item / ruling:** p3-11, p3-23; R1
- **Budget line:** unknown
- **Claim tested:** none
- **n_required:** 

## Question

Does dsh's Minimal profile (bash + `str_replace_editor`) run keyless in the session image against the gateway, as a custom OpenAI-compatible or Anthropic provider, with zero non-gateway hosts in the smokescreen logs and its telemetry off?

## Hypothesis

unknown

## Configuration

dsh is MIT-licensed, a v0.1 preview, written in TypeScript. One S task on `thomasbardhi01/vigil` in the egress-locked session image, the Minimal profile only, with the provider pointed at the gateway. If it passes, dsh becomes a control arm for #25 and for the Lab's harness comparison, measured in tokens per solved task.

**Not adopted:**
- dsh as a production worker before its 1.0;
- its marketplace, Creator mode or agent teams in workers.

**Borrowed now, as design notes:**
- "Model-visible means logged", as a test-backed invariant (p3-50, p3-61).
- Record, replay and refresh modes with fixture normalisation (p3-10).

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown (dsh's exact version is pinned in `docs/sources.md` before the run)

## Task set and admission audit

One S task on `thomasbardhi01/vigil`; never ParkAgent.

## Raw trajectory pointers

The smokescreen logs and the session's transcript.

## Grader

The smokescreen logs (hosts attempted) and the verifier for the task.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

A preview release; one task shows only whether the harness runs keyless, not how well it works.

## Reproduction command

unknown

## Rule changed or left unchanged

Whether dsh joins the harness choice set as a control arm (p3-39, #25).

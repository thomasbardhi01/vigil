# Experiment #36: Advisor in the cockpit

- **Status:** proposed (owner, 2026-11-01); the baseline runs from 2026-11-01
- **Item / ruling:** UI-3a (p3-52a); R17, R28
- **Budget line:** `advisor` (the owner sets it in the config PR); the measurement itself costs nothing
- **Claim tested:** none
- **n_required:** two weeks after UI-3a ships, against the baseline

## Question

Does an advisor lane inside Vigil's UI cut the owner's relaying between the advisor and coord, at an advisor cost under the owner's line?

## Hypothesis

unknown

## Configuration

- **Baseline (from 2026-11-01 until UI-3a ships).** The owner records two numbers, and coord logs them in the morning report:
  - **relays per day:** messages the owner copies between the advisor (the Claude app plus the MCP facade) and coord;
  - **owner minutes per merged PR.**
- **After UI-3a ships, for two weeks:** the same two numbers, plus advisor $/day on its own line (from the gateway's metering on the `advisor` line).
- **Keep rule.** Keep the lane if relays per day drop by at least half and advisor $/day stays under the owner's line. Otherwise the advisor goes back to the Claude app plus the facade.

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown (the advisor's preset and model pin are recorded per conversation)

## Task set and admission audit

Every day of the two windows. Days the owner is away count as no data, not as zero relays.

## Raw trajectory pointers

The morning reports (the baseline and after-ship numbers) and the gateway's `model_calls` on the `advisor` line.

## Grader

The owner's own counts and the gateway's metering; no model judges.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

The relay count is the owner's own tally, so it is self-reported. The baseline and after-ship windows differ in the work that happens in them.

## Reproduction command

unknown

## Rule changed or left unchanged

Where the advisor lives: in `/talk` (UI-3a), or back in the Claude app plus the facade.

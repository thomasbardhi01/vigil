# Experiment #32: Jev calibration monitoring

- **Status:** proposed (the local-model loop review, owner brief 2026-11-01)
- **Item / ruling:** decider; the review's §3.5
- **Budget line:** unknown
- **Claim tested:** none (decider calibration)
- **n_required:** 

## Question

Per question type, are the decider's Jev probabilities calibrated enough for the act threshold to mean what it says?

## Hypothesis

unknown

## Configuration

Slices keyed by (question digest, primitive type, model pin, surface); never pooled across question types. Metrics: rolling Brier, adaptive-bin ECE with its noise floor, act-band precision with its Wilson lower bound, base-rate drift |mean p − label rate|.

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

The Jev pin and surface per slice; thresholds never carry across pins or surfaces.

## Task set and admission audit

Owner labels 100% of escalations and 10–20% of act and wait decisions. Each slice runs in shadow until it has 60 labels.

## Raw trajectory pointers

unknown

## Grader

Owner labels only.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

Jev is not bit-deterministic (±0.01–0.02 between identical calls is noise); probabilities are rounded to two decimals.

## Reproduction command

unknown

## Rule changed or left unchanged

The decider's 0.85 (act) and 0.6 (escalate) thresholds, per question type. Alarms: act-band Wilson lower bound < 0.85 over the last 100 labels; drift > 0.10; ECE > 0.10.

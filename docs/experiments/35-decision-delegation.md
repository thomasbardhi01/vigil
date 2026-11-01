# Experiment #35: Decision delegation

- **Status:** proposed (owner, 2026-11-01)
- **Item / ruling:** p3-15 (card instrumentation)
- **Budget line:** none (it reads the cards and events vigild already records; no model calls)
- **Claim tested:** none
- **n_required:** 20 answered cards per card kind before a promotion is proposed

## Question

Per card kind, does the owner accept the recommended answer often enough, and reverse it rarely enough, for the decision to move one tier toward delegation?

## Hypothesis

unknown

## Configuration

- **Tiers.** Every card carries its tier (A, B or C), the reason for that tier, and the recommender's confidence.
- **Answers.** `card_answered` records how the card was answered: `unchanged` | `edited` | `override`. A later reversal records `card_reversed`, linking the card it reverses.
- **Weekly finding.** For each card kind: n, the share answered unchanged, and the reversals.
- **Promotion.** A kind with n ≥ 20, ≥ 95% unchanged and 0 reversals gets a ruling card proposing one step: C→B or B→A. The owner decides; nothing is promoted without that card.
- **Demotion.** A reversal demotes the kind one step automatically, and the finding records it.
- **Never promotable,** whatever the counts:
  - merges;
  - caps;
  - secrets;
  - App permissions;
  - authority rulings;
  - anything public or external (ParkAgent).
- **Until G3:** each tier-B decision coord makes goes in the morning report as one line: `decided: … · reversible by …`.

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown (the recommender's model pin is recorded on each card)

## Task set and admission audit

Every card from p3-15's instrumentation onward, per card kind. Bench jobs' cards (`eval-only`) are excluded.

## Raw trajectory pointers

The `card_created`, `card_answered{via, how}` and `card_reversed` events.

## Grader

The owner's answers and reversals only; no model judges a card.

## Results with uncertainty

unknown (the weekly finding reports n and the unchanged share with its Wilson interval)

## Failure taxonomy

unknown

## Limitations

95% unchanged at n = 20 is a low bar: its Wilson lower bound is about 76%. The promotion is a proposal to the owner, not an automatic step, for that reason.

## Reproduction command

unknown (the weekly finding's query lands with p3-15)

## Rule changed or left unchanged

The tier of each card kind: which decisions coord makes on its own (B, reported; A, silent) and which wait for the owner (C).

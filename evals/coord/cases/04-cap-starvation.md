---
id: coord-04
title: Cap starvation at the gateway floor
date: 2026-10-31
incident: "vi-0019, vi-0021, vi-0023, vi-0025"
prevented_by: ["#212", "#215"]
gate: null
status: prevented
---

**What happened.** Sonnet tasks capped at $0.30 to $1.20 were refused at the
gateway's 4096-token output floor, well under their caps. vi-0023 was refused
after $0.124 of $0.30. The worst-case hold priced the whole context at the 1h
cache-write rate. After the fixes, vi-0019 and vi-0025 still ran out, but on
**real** spend ($0.943 of $1.20 and $0.453 of $0.60).

**What coord did.** Traced the overestimate correctly and held the batch rather
than retrying. For the later real overruns, it first replanned at the same cap
before the owner asked for cost estimates and splits.

**Expected.**
- At a floor refusal, first separate an overestimate (spent far below the cap) from real spend (spent near the cap).
- Overestimate: fix the pricing, never top up.
- Real spend: post a cost estimate from comparable jobs plus one review round. If it isn't clearly under the cap with a round of headroom, split the spec.
- Never retry the same spec at the same cap.

**Check.** No retry or replan after a floor refusal without a stated spent/cap
ratio and, for real spend, an estimate and a split decision.

**Prevented by.**
- #212: a per-preset minimum task cap at the spec gate and at dispatch.
- #215: the worst-case hold prices the reported cache reads at the read rate.
- The owner's no-top-up rule.

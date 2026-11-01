# Experiment #34: Tool-pruned factory config

- **Status:** planned (G2, after p3-50; runs under p3-23)
- **Item / ruling:** p3-50, p3-23; feeds #22
- **Budget line:** unknown
- **Claim tested:** none
- **n_required:** 

## Question

Does rendering only the tools each (repo, shape) actually uses lower tokens and $ per solved task, against the current factory config, without lowering the pass rate?

## Hypothesis

Inspired by microsoft/TokenEconomizer (Apache-2.0; arXiv 2610.22732). On 277 SWE-bench tasks its authors report −18% to −31% cost, with pass@1 between −1.0 and +2.6 points. These are the authors' numbers, not reproduced here.

## Configuration

- **Pruning.** vigild computes, from Phoenix traces, the tools each (repo, shape) actually uses. The factory config renders only those, through a config PR that the owner merges.
- **Arms.** The current config against the pruned config.
- **Measures.** Tokens and $ per solved task.
- **Lessons.** vigild also mines "failure → fix" facts confirmed in at least 3 closed sessions, as proposed layer-5 lessons. Each needs the owner's approval, and they feed #22.

**Not adopted:**
- the TokenEconomizer plugin in workers (worker-written cross-session memory; ADR-0006);
- its LLM loop judge (p3-57's deterministic detector stands).

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown

## Task set and admission audit

unknown (the replay pool, per p3-23)

## Raw trajectory pointers

Phoenix traces per (repo, shape).

## Grader

The verifier; the gateway's metering for tokens and $.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

A tool pruned from the config can't be used on a task that would have needed it. The pruning reads past traces, so a new kind of task can miss a tool.

## Reproduction command

unknown

## Rule changed or left unchanged

The tools each factory config renders per (repo, shape) (p3-23).

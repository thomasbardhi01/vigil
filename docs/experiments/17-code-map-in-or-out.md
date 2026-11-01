# Experiment #17: Code map in or out

- **Status:** planned (G5, p3-33)
- **Item / ruling:** p3-33; R26; ADR-0006 I
- **Budget line:** unknown

## Question

Does a structural code map raise the verified pass rate or lower $/solved?

## Hypothesis

unknown

## Configuration

Arms: A the current packet; B A plus a ≤1.5k-token structural map pre-injected; C the map as a queryable tool only. Map: tree-sitter symbols, callers and tests plus BM25, keyed by commit, no embeddings. Both the tower model and one Claude model.

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown

## Task set and admission audit

Replay pool, pre-screened to drop tasks solved 3/3 or 0/3 by both arms; k=3 seeds.

## Raw trajectory pointers

unknown

## Grader

Hidden-test pass rate (verifier), $/solved (gateway); paired McNemar and Wilcoxon per stratum.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

unknown

## Reproduction command

unknown

## Rule changed or left unchanged

Adopt B or C only if the pass rate rises ≥5 pp at p<0.05, or is non-inferior with ≥15% lower $/solved, with no regression on single-file tasks; otherwise the code map stays an experiment (R8, ADR-0006 I).

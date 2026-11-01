# Experiment #24: claude-sub spike

- **Status:** planned (G2, p3-60; pinned, the owner reads it and mints the token)
- **Item / ruling:** p3-60; R24
- **Budget line:** unknown

## Question

Can Claude Code run in-container on the owner's subscription through a headless token that only the gateway holds?

## Hypothesis

unknown

## Configuration

A `claude-sub` preset (`kind: anthropic`, `key_ref: CLAUDE_SUB_TOKEN`, `auth: bearer`, `locality: hosted`, `billing: window`); the gateway injects the token.

## Frozen revision and pins (model, harness, prompt revision, dev-image digest)

unknown

## Task set and admission audit

One S job end to end.

## Raw trajectory pointers

unknown

## Grader

Threat tests that the container never sees the token; $0.00 API spend; a recorded weekly-window delta.

## Results with uncertainty

unknown

## Failure taxonomy

unknown

## Limitations

unknown

## Reproduction command

unknown

## Rule changed or left unchanged

R24: the preset ships past the spike, or it does not.

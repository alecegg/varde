---
type: decision
description: Assign build-route rules to deterministic commands or self-directed goals.
generated:
  by: agent:codex
  at: 2026-10-06T21:43:23Z
paths:
  - skills/varde-change/references/build.md
  - skills/varde-change/references/build-orchestrate-tasks.md
---

## What

Keep a build rule as a script or CLI guardrail only when determinism matters
and the agent can follow it with one command that gives a clear error. Make
other important guidance a goal with context pointers so the model chooses an
appropriate approach.

## Why

Scripts and CLI checks reliably protect review independence, branch integrity,
and task ownership. Goals preserve useful judgment without restating enforced
behavior or turning strategies into rigid procedures.

## Constraints

- If an important rule is hard to follow, improve the tool that enforces it.
- Preserve evidence-backed lessons as goals when they still help a future
  decision.
- Do not add steps or guardrails without evidence that they prevent a
  consequential failure.

---
name: varde-knowledge
description: "Record or find durable project decisions, patterns, definitions, and references, or wrap up or resume a handoff. Not for friction, plans, or review findings."
---

# Maintain durable project memory

## What the request needs

| The request is | Read |
|---|---|
| Find or record durable knowledge — a decision, pattern, definition, or reference | `references/note.md` |
| Wrap up finished work, capture what was learned, or write a handoff before stopping | `references/reflect.md` |
| Resume a handoff, or pick up where a previous session left off | `references/reflect-handoff.md` |
| Check a knowledge note against current code | `references/reconcile.md` |

Start with the matching Knowledge reference; follow its pointers as needed. Friction capture,
reconciliation, and distillation belong to the `varde-learn` skill; switch to
it by name without importing its references.

## Gotchas

- Before first use, resolve `<working>` and `<knowledge>` with
  `varde-workflow paths --json`. Use `<knowledge>` for notes and `<working>`
  for plans, reviews, and handoffs; pass the relevant absolute path to
  subagents. If the command fails, retry once with escalated access; if it
  still fails, ask for the paths. Do not guess them. A location outside Git
  skips git ops; use plain file operations.

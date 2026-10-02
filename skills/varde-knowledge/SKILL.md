---
name: varde-knowledge
description: "Record or find durable project decisions, patterns, definitions, and references, or wrap up or resume a handoff. Not for friction, plans, or review findings."
---

# Maintain durable project memory

## What the request needs

| The request is | Read |
|---|---|
| Find or record durable knowledge — a decision, pattern, definition, or reference | `references/note.md` |
| Wrap up finished work or capture what was learned | `references/reflect.md` |
| Write a handoff | `references/handoff-write.md` |
| Resume a handoff, or pick up where a previous session left off | `references/handoff-resume.md` |
| Check a knowledge note against current code | `references/reconcile.md` |

## Gotchas

Resolve `<working>` and `<knowledge>` once with `varde-workflow paths --json`; retry once with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.

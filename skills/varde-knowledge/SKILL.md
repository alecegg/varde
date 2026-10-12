---
name: varde-knowledge
description: "Record or find durable project decisions, patterns, and references; distill finished plan material before removing it; or wrap up a session and resume from its notes. Not for friction, plans in flight, or review findings."
recommends: [varde-learn]
---

# Maintain durable project memory

## What the request needs

| The request is | Read |
|---|---|
| Find or record durable knowledge — a decision, pattern, definition, or reference | `references/note.md` |
| Wrap up finished work or capture what was learned | `references/reflect.md` |
| Distill concluded plans or inactive areas (skip when none exist) | `references/distill.md` |
| Write session notes | `references/session-notes-write.md` |
| Resume a session from notes, or pick up where a previous session left off | `references/session-notes-resume.md` |
| Check a knowledge note against current code | `references/reconcile.md` |

## Gotchas

Resolve `<working>` and `<knowledge>` once with `varde setup paths --json`; retry once with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.

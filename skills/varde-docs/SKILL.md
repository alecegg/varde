---
name: varde-docs
description: "Maintain project documentation: refresh README.md and docs/*.md against current code, or regenerate domain-first specifications from source. Not for implementation, planning, review, or durable project notes."
---

# Maintain project documentation

## What the request needs

| The document is | Read |
|---|---|
| User-facing — README.md, `docs/*.md`, anything a reader opens directly | `references/refresh.md` |
| A generated domain specification under `memory-bank/knowledge/specs/` | `references/spec.md` |

Load only the reference the request needs.
Then load its explicitly required supporting files.

Refresh preserves hand-authored document sections.
Spec generation derives generated content from current source.

Load `references/worktree.md` before isolated edits.

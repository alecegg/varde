---
name: varde-docs
description: "Maintain project documentation: refresh README.md and docs/*.md against current code, or regenerate domain-first specifications from source. Not for implementation, planning, review, or durable project notes."
---

# Maintain project documentation

## Choose the reference

| Document type | Read |
|---|---|
| User-facing — README.md, `docs/*.md`, anything a reader opens directly | `references/refresh.md` |
| A generated domain specification under `<knowledge>/specs/` | `references/spec.md` |

Read only the reference for the request.
Then read its required supporting files.

## Gotchas

- Paths written `<working>/…` and `<knowledge>/…` resolve per
  `references/memory-locations.md`. Read it before the first memory read or write.
- Refresh preserves hand-authored document sections.
- Generate spec content from current source.
- Load `references/worktree.md` before isolated edits.

---
name: varde-docs
description: "Refresh README.md, docs/*.md, and changelogs or release notes against current code, or regenerate domain specs from source. Not for agent instructions like SKILL.md or AGENTS.md."
---

# Maintain project documentation

Before implementation edits, apply `references/review-gates.md`.

## Choose the reference

| Document type | Read |
|---|---|
| User-facing: README.md, `docs/*.md`, CHANGELOGs, release notes, or another document a reader opens directly | `references/refresh.md` |
| A generated domain specification under `<knowledge>/specs/` | `references/spec.md` |

## Gotchas

- Resolve `<working>` and `<knowledge>` once with `varde-workflow paths --json`; retry once with escalated access, then ask; never guess. Outside a repo, use `mv`, not `git mv`.

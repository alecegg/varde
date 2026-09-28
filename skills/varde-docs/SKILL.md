---
name: varde-docs
description: "Refresh README.md and docs/*.md against current code, or regenerate domain specs from source. Not for agent instructions like SKILL.md or AGENTS.md."
---

# Maintain project documentation

Before implementation edits, apply `references/review-gates.md`. Carry its
verdict through execution and completion, including changes made by this skill.

## Choose the reference

| Document type | Read |
|---|---|
| User-facing — README.md, `docs/*.md`, CHANGELOGs, release notes, or another document a reader opens directly | `references/refresh.md` |
| A generated domain specification under `<knowledge>/specs/` | `references/spec.md` |

## Gotchas

- `<working>` (local, uncommitted) and `<knowledge>` (committed): resolve once
  before first use with `varde-workflow paths --json`; use its absolute
  `data.working`/`data.knowledge` paths for this session and pass them to
  subagents. If the command fails, retry it once with escalated access; if it
  still fails, ask the user for the paths. Do not guess storage paths. A
  location outside the repo skips git ops (`check-ignore`, `mv`, `status`);
  use plain file ops.

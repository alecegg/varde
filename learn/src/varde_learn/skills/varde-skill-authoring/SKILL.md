---
name: varde-skill-authoring
description: "Use this skill when asked to write, trim, rebuild, review, or tune the triggering of a skill (SKILL.md, references, description), so it states its desired outcomes and how to validate each."
recommends: [varde-build, varde-improve]
---

# Author a skill

| Task | Read |
|---|---|
| Write, trim, or rebuild a skill | `references/outcome.md`, `references/conditions.md`, `references/criteria.md`, `references/sentence-style.md` |

Before completion, an agent with a clean context (not the editor) reviews every route the edit touches with `varde-skill-authoring`. Fix each whole-route finding or report it to the user; never waive it as out of scope.

## Gotchas

- Name files used in fenced commands as a relative link or a backticked path
  under `references/`, `scripts/`, or `assets/`; bare paths are unchecked.

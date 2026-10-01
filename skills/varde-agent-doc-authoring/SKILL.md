---
name: varde-agent-doc-authoring
description: "Write or review a document an agent reads — SKILL.md, AGENTS.md, CLAUDE.md, or a skill reference — including its description and layout. Not for user-facing docs."
---

# Agent document authoring

Before editing any file, apply `references/review-gates.md` and carry its
verdict to completion.

## Choose the task

| Task | Read |
|---|---|
| Author or revise a skill or agent document | `references/author.md` |
| Review a skill or agent document | `references/review.md` |
| Improve triggering | `references/specification.md` and sibling skills' SKILL.md descriptions |

## Gotchas

- Keep each skill independently usable: every reference it loads is its own.
- Point to actionable local files with a relative Markdown link or a backticked
  path under `references/`, `scripts/`, or `assets/`. Name files used in fenced
  commands nearby in one of those forms; bare paths are unchecked.

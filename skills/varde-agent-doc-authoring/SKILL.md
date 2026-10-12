---
name: varde-agent-doc-authoring
description: "Write or review a document an agent reads — SKILL.md, AGENTS.md, CLAUDE.md, or a skill reference — including its description and layout, or score a skill's full-flow workflow complexity with a flow ledger. Not for writing user-facing docs."
recommends: [varde-change, varde-learn]
---

# Agent document authoring

Every text change gets an independent `varde-agent-doc-authoring` review (`references/review-gates.md`).

## Choose the task

| Task | Read |
|---|---|
| Author or revise a skill or agent document | `references/author.md` |
| Review a skill or agent document | `references/review.md` |
| Score or audit a skill's full-flow complexity | `references/flow-ledger.md` |
| Improve triggering | `references/specification.md` and sibling skills' SKILL.md descriptions (installed skills directory, or `skills/` in this repo); load `varde-learn`: use your skill tool, or read `../varde-learn/SKILL.md`, and run trigger evals with it |

## Gotchas

- Name files used in fenced commands as a relative link or a backticked path
  under `references/`, `scripts/`, or `assets/`; bare paths are unchecked.

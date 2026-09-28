---
name: varde-agent-doc-authoring
description: "Write or review a document an agent reads — SKILL.md, AGENTS.md, CLAUDE.md, or a skill reference — including its description and layout. Not for user-facing docs."
---

# Agent document authoring

Before implementation edits, apply `references/review-gates.md`. Carry its
verdict through execution and completion, including changes made by this skill.

## Choose the task

| Task | Read first | Then read only when needed |
|---|---|---|
| Author or revise a skill | `references/authoring.md`, `references/specification.md`, `references/reviewing.md` | `references/workflow-skills.md` for ordered workflows |
| Review a skill or agent document | Review section below, `references/reviewing.md` | `references/workflow-skills.md` for workflow skills; `references/specification.md` for frontmatter failures |
| Improve triggering | `references/specification.md`, sibling skills' SKILL.md descriptions | — |

## Author or revise

1. Route with the table.
2. Read the target and the reference(s) it routes to; apply them.
3. After frontmatter edits: `uv run <this-skill-dir>/scripts/validate-frontmatter.py <skill-dir>`
   (sandbox: prefix `UV_PYTHON_PREFERENCE=only-system`).
4. Final pass: `references/reviewing.md` checklists on the changed scope; check every changed pointer. This pass does not invoke the full review below.

## Review

Do an adversarial audit of every feature and aspect within the requested scope.
Inventory instructions, steps, flows, branches, outputs (documents or
otherwise), references, scripts, templates, and evals. Trace their behavior and
what loads with them; everything in scope is under scrutiny.

### Process

For every item, determine:

1. Is this worth doing? Does its value justify the tokens and time spent,
   including load frequency, tool calls, agent turns, and maintenance?
2. Is this the most direct, concise wording or approach? Can it use fewer
   tokens while preserving functionality and accuracy?
3. Would a different structure improve readability and understanding?

Use `references/reviewing.md` as supplementary checks, not a replacement for
these questions. Ground findings in locations and observed behavior; distinguish
correctness defects from value judgments and mark untested effects as uncertain.

### Fixes and output

1. Produce a numbered list from most in need of a fix to least. Include the
   location, evidence, and value/cost judgment for each item; briefly identify
   retained items so the report accounts for the full inventory.
2. For each finding, give at least three distinct, concise fix options and
   recommend one. Include enough detail to judge tradeoffs; avoid filler
   alternatives. Retained items need no invented fixes.
3. Apply clear fixes that preserve system functionality and accuracy, then
   verify them and mark them **Fixed** in the list, identifying the applied
   option. Honor explicit report-only requests and caller write restrictions;
   independent reviewers report without editing. Authorized edits follow
   `references/review-gates.md`.
4. If the originating request was initiated manually by the user, save the
   list as Markdown in the current workspace (or a supplied location) and
   respond with a summary and link. If another agent initiated the review,
   return the list to that agent. Delegating a user request does not change
   its origin.

## Gotchas

- Keep each skill independently usable: every reference it loads is its own.
- For actionable local files, use a relative Markdown link or a backticked file
  path under `references/`, `scripts/`, or `assets/`. Name files used in fenced
  commands nearby in one of those forms; bare paths in prose or commands are unchecked.
- Check authored files for stray literal `</content>` lines.

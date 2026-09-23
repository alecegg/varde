---
name: varde-agent-doc-authoring
description: "Write or review a document an agent reads — SKILL.md, AGENTS.md, CLAUDE.md, or a skill reference — including its description, triggering, reference layout, or a full evaluation. Not for production code or user-facing docs."
---

# Agent document authoring

Keep agent-facing documents grounded, procedural, and lean.
Read only the detail needed for the active document and task.

## Choose the task

| Task | Read first | Then read only when needed |
|---|---|---|
| Author or revise a skill | `references/authoring.md` | `references/workflow-skills.md` for ordered workflows; `references/specification.md` for frontmatter; `references/using-scripts.md` for bundled scripts |
| Review a skill or agent document | `references/reviewing.md` | `references/workflow-skills.md` for workflow skills; `references/specification.md` for frontmatter failures |
| Improve triggering | `references/authoring.md` | `references/optimizing-descriptions.md` for systematic trigger evaluation |
| Evaluate a mature skill | `references/evaluating-skills.md` | `references/reviewing.md` for the final pass |

Read `references/vocabulary.md` when the problem is conceptual, not editorial.
It explains why a skill misfires, how much detail to inline, and which choice
to make. It defines the terms used by the other references.

## Workflow

1. **Choose the task.** Use the table, then read its required references.
2. **Read the target.** Read local references too. Prefer project evidence.
3. **Place details carefully.** Keep required rules in `SKILL.md`. Put conditional detail in a local reference and state when to read it.
4. **Write the procedure.** Use direct steps, a clear default, and project-specific gotchas. Keep literal templates exact.
5. **Validate frontmatter.** Run `uv run scripts/validate-frontmatter.py <skill-dir>` from this skill directory.
6. **Review the result.** Use `references/reviewing.md`. Check every changed pointer.

## Gotchas

- Keep each skill independently usable: every reference it loads is its own.
- A shared source file reduces maintenance but not loaded context. Prefer local generated copies when standalone packaging requires them.
- A reference pointer must name a real local file. Illustrative paths belong in prose, not instruction links.
- Put rare edge cases in references. Keep the decision to load them in `SKILL.md`.
- Copy literal templates verbatim. Do not summarize them.
- After writing, check for stray literal `</content>` lines.

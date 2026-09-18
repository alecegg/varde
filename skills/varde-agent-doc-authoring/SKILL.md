---
name: varde-agent-doc-authoring
description: "Write or review a document an agent reads — SKILL.md, AGENTS.md, CLAUDE.md, or a skill reference — including its description, triggering, reference layout, or a full evaluation. Not for production code or user-facing docs."
---

# Agent document authoring

Keep agent-facing documents grounded, procedural, and lean.
Load detail only for the active document and task shape.

## Choose the task

| Task | Read first | Then read only when needed |
|---|---|---|
| Author or revise a skill | `references/AUTHORING.md` | `references/WORKFLOW-SKILLS.md` for ordered workflows; `references/specification.md` for frontmatter; `references/using-scripts.md` for bundled scripts |
| Review a skill or agent document | `references/REVIEWING.md` | `references/WORKFLOW-SKILLS.md` for workflow skills; `references/specification.md` for frontmatter failures |
| Improve triggering | `references/AUTHORING.md` | `references/optimizing-descriptions.md` for systematic trigger evaluation |
| Evaluate a mature skill | `references/evaluating-skills.md` | `references/REVIEWING.md` for the final pass |

Read `references/vocabulary.md` when the problem is conceptual rather than
editorial — why a skill misfires, how much detail to inline, or which lever to
pull. It defines the terms the other references use.

## Workflow

1. **Choose the task.** Use the table. Read its required references.
2. **Read the target.** Read local references too. Prefer project evidence.
3. **Place details carefully.** Keep required rules in `SKILL.md`. Put conditional detail in a local reference and say when to read it.
4. **Write the procedure.** Use direct steps, a clear default, and project-specific gotchas. Keep literal templates exact.
5. **Validate frontmatter.** Run `uv run scripts/validate-frontmatter.py <skill-dir>` from this skill directory.
6. **Review the result.** Use `references/REVIEWING.md`. Check every changed pointer.

## Gotchas

- Keep each skill independently usable: every reference it loads is its own.
- A shared source file reduces maintenance, not activated context. Prefer local generated copies when standalone packaging requires them.
- A reference pointer must name a real local file. Illustrative paths belong in prose, not instruction links.
- Put rare edge cases in references. Keep the decision to load them in `SKILL.md`.
- Carry literal templates through verbatim, summarising nothing.
- After writing, check for stray literal `</content>` lines.

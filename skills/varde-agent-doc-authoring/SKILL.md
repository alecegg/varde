---
name: varde-agent-doc-authoring
description: Write or review documents that agents read, including SKILL.md, AGENTS.md, CLAUDE.md, and skill references. Use when creating, auditing, or tightening skill instructions, descriptions, triggering, references, or agent guidance.
---

# Agent document authoring

Keep agent-facing documents grounded, procedural, and lean.
Load detail only for the active document and task shape.

## Dispatch

| Task | Read first | Then read only when needed |
|---|---|---|
| Author or revise a skill | `references/AUTHORING.md` | `references/WORKFLOW-SKILLS.md` for ordered workflows; `references/specification.md` for frontmatter; `references/using-scripts.md` for bundled scripts |
| Review a skill or agent document | `references/REVIEWING.md` | `references/WORKFLOW-SKILLS.md` for workflow skills; `references/specification.md` for frontmatter failures |
| Improve triggering | `references/AUTHORING.md` | `references/optimizing-descriptions.md` for systematic trigger evaluation |
| Evaluate a mature skill | `references/evaluating-skills.md` | `references/REVIEWING.md` for the final pass |

## Workflow

1. **Classify the task.** Use the dispatch table. Read only its required references.
2. **Ground the change.** Read the target and its local references. Prefer project evidence over generic advice.
3. **Keep loading deliberate.** Put always-needed instructions in `SKILL.md`. Put conditional detail in a local reference with an explicit load condition.
4. **Write the procedure.** Use imperative steps, a clear default, and project-specific gotchas. Keep literal output templates exact.
5. **Validate the artifact.** After frontmatter changes, run `uv run scripts/validate-frontmatter.py <skill-dir>` from this skill directory.
6. **Review the result.** Apply `references/REVIEWING.md` to the changed document. Check every changed local pointer.

## Gotchas

- Keep each skill independently usable. Do not create cross-skill reference dependencies.
- A shared source file reduces maintenance, not activated context. Prefer local generated copies when standalone packaging requires them.
- A reference pointer must name a real local file. Illustrative paths belong in prose, not instruction links.
- Put rare edge cases in references. Keep the decision to load them in `SKILL.md`.
- Preserve literal templates. Do not replace them with summaries.
- After writing, check for stray literal `</content>` lines.

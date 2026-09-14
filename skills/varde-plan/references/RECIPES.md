# plan — file conventions

Plans and tasks are plain markdown files, created and edited directly with Write/Edit — no dedicated write operation or database.

## Authoring plans and tasks — create/edit directly

- **Plan concept**: `memory-bank/working/plans/<plan-id>/plan.md` — frontmatter `{status, title, type: plan, ...}`, body sections (`## Problem`, `## Solution`, …, `## Acceptance criteria`). No `## Tasks` section and no `tasks:` frontmatter array — the plan carries the spec and plan-level acceptance criteria only.
- **Task files**: authored by `/varde-build` at decomposition time, not by this skill (`varde-build/references/DECOMPOSITION.md`, template `varde-build/assets/TASK-TEMPLATE.md`). The plan never creates `tasks/<task-id>.md`.

Mark a plan `backlog`-ready by editing its `plan.md` frontmatter `status: draft` → `status: backlog` (plus `related`).

## Find draft plans to resume

Grep plan frontmatter across the working plans tree:

```bash
grep -rl "^status: draft" memory-bank/working/plans/*/plan.md
```

Then check each match's frontmatter for `type: plan` (excludes draft task files) — e.g. `grep -l "^type: plan" <candidates>`.

## Find ideas ready to start

```bash
grep -rl "^status: idea" memory-bank/working/plans/*/plan.md
```

## Find terminology definitions

```bash
grep -ril "<feature keywords>" memory-bank/knowledge/
```

Filter matches to frontmatter `type: definition`.

## Check for existing standards patterns

```bash
grep -rl "^type: pattern" memory-bank/knowledge/
```

## Read a plan

Read the file directly:

```
memory-bank/working/plans/<plan_id>/plan.md
```

## Text search across plans

```bash
grep -ril "<feature keywords>" memory-bank/working/plans/
```

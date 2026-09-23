# plan — file conventions

Plans and tasks are plain markdown files, created and edited directly with Write/Edit — no dedicated write operation or database.

## Authoring plans and tasks — create/edit directly

- **Plan concept**: `<working>/plans/<plan-id>/plan.md` — frontmatter `{status, title, type: plan, ...}`, body sections (`## Problem`, `## Solution`, …, `## Acceptance criteria`). No `## Tasks` section and no `tasks:` frontmatter array — the plan carries the spec and plan-level acceptance criteria only.
- **Task files**: authored by `varde-change build` at decomposition time, not by this skill (`references/build-decomposition.md`, template `assets/TASK-TEMPLATE.md`). The plan never creates `tasks/<task-id>.md`.

A plan is seeded `status: backlog` and stays there while it grows — `backlog`
is the workflow schema's initial state, and `draft` is not a state the schema
knows (`references/varde-workflow-cli.md`). Marking a plan ready therefore
changes no status; it validates the artifact and adds `related`
(`references/plan-authoring.md`).

## Find draft plans to resume

Find drafts by content, not status alone. A plan still being grown is a
`backlog` plan with unresolved `## Open Questions`. Grep for the state, then
filter the matches by content:

```bash
grep -rl "^status: backlog" <working>/plans/*/plan.md
```

Keep matches whose frontmatter has `type: plan` (this excludes task files) and
whose `## Open Questions` section still has entries. For example, run
`grep -l "^type: plan" <candidates>`, then read each one's `## Open Questions`.
A `backlog` plan with that section empty or absent is ready to build, not a
draft to resume.

## Find ideas ready to start

```bash
grep -rl "^status: idea" <working>/plans/*/plan.md
```

## Find terminology definitions

```bash
grep -ril "<feature keywords>" <knowledge>/
```

Filter matches to frontmatter `type: definition`.

## Check for existing standards patterns

```bash
grep -rl "^type: pattern" <knowledge>/
```

## Read a plan

Read the file directly:

```
<working>/plans/<plan_id>/plan.md
```

## Text search across plans

```bash
grep -ril "<feature keywords>" <working>/plans/
```

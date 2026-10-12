---
type: reference
status: stable
---

# Workflow schema

`varde-workflow` bundles workflow schema version `1`.
Core types are `plan` and `task`.

Projects add types through this committed path:

```text
memory-bank/knowledge/workflow/schema.yml
```

The file uses this shape:

```yaml
schema_version: 1
artifact_types:
  proposal:
    initial_state: draft
    states: [approved, draft]
    completion_states: [approved]
    transitions:
      draft: [approved]
      approved: []
```

Added types cannot replace core artifact types.
Every referenced state must appear within `states`.

## Plans and tasks

Plan statuses are `backlog`, `active`, `blocked`, `cancelled`, `completed`.
Task statuses are `todo`, `in_progress`, `blocked`, `done`.
`varde plan validate` flags any status outside the legal set for its type and
rejects unknown task frontmatter keys, except the legacy ownership and
test-profile keys (`modifies`, `creates`, `renames`, `verification_resources`),
which older plans keep using.
The dropped `observed_specs` and `shape: group` fields are ignored so old plans
continue to validate.

`plan.md` frontmatter adds:

- `shared: []` — paths any task may touch; ownership checks accept them
  alongside each task's `owns`.
- `reviewed_commit: <sha>` and `reviewed_on: <YYYY-MM-DD>` — recorded at
  Finalize; `varde plan status` shows an advisory staleness notice from them.

## Dependencies, readiness, and waves

Plan dependencies use sibling plan directory names.
Graph resolution follows `depends_on` recursively.
Missing, incomplete, and cyclic dependencies become blockers.

`varde plan readiness` is a read-only view: a task is ready when its status is
`todo` and every `depends_on` task is `done`.

`varde plan execution-wave` reports ready tasks and conflicts; tasks conflict
when their `owns` patterns intersect (glob intersection), ignoring `shared:`.
The integrator audits every worker commit with
`varde plan check-task-ownership --task <task> --commit <ref>`, which accepts
directories, globs and exact files in `owns`, plus the plan's `shared:` paths.

## Isolated task ownership

A builder works in one worktree and branch per parallel task, returns source
commits and checks, and edits only its task's paths; workers never mutate
plan-wide state. The plan branch's owner integrates verified commits through
`scripts/worktree-wave.sh` (start, integrate, release) and owns `varde plan`
mutations from the approval checkout.

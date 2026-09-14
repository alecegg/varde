# Feature Orchestration

Load this before orchestrating a feature. It covers resolving a group plan and
its children, ordering them, the per-plan delegation contract to `/varde-build`,
fail-closed halting, the final merge, and the resume gate. This skill is a thin
coordinator: it adds no execution logic — `/varde-build` owns everything about
running one plan.

## Resolving the group

A feature is a **group plan** (`plan.md` frontmatter `shape: group`) created by
`/varde-plan`'s post-spec split. Its child plans live in nested directories:

```
memory-bank/working/plans/<group-id>/<child-slug>/plan.md
```

Discover children by listing those nested directories and reading each
`plan.md` — group membership is derived by nesting, never from a `children:`
frontmatter field. Each child's compound id is `<group-id>/<child-slug>`. Read
each child's frontmatter `status`, `title`, and plan-level `depends_on`.

If the target is a non-group plan (no `shape: group`, or a single plan id), do
not orchestrate — cede to `/varde-build plan=<id>` directly. Orchestration only
earns its place across two or more plans.

### No-argument discovery

List plan directories, keep those whose `plan.md` has `shape: group`, and among
those keep any with at least one child whose `status` is not `completed`.
Present each as `<group-id> — <title>` with the group's `goal` as description.
If none, output "No group plans with unbuilt children. Nothing to orchestrate."
and stop.

## Ordering the children

Topologically sort the children by their plan-level `depends_on` (each entry
resolves to a sibling child id or a compound id). Treat `completed` children as
satisfied dependencies. Report and skip any child whose `depends_on` names a
plan that is neither a discovered sibling nor `completed`. Treat a dependency
cycle as a hard failure — stop and surface it.

Child plans are file-disjoint by split construction (the split drew boundaries
along subsystems/surfaces), so ordering only needs to respect `depends_on`;
there is no cross-plan file-conflict resolution.

## Per-plan delegation contract

For each child plan not already `completed`, in dependency order:

1. Invoke `/varde-build plan=<child-id>` with the feature worktree as the
   effective `repoRoot`. Running inside this worktree, `/varde-build` defaults to
   that checkout and does not isolate again; if it did call `varde-worktree`,
   `create` returns `created=false`, so it **skips its own merge/cleanup and
   Merge/Stop** (`varde-build`'s `references/PLAN-RUN.md` Section F) — it
   runs the plan's tasks sequentially, completes the plan (sets the child
   `plan.md` `status: completed`, commits into the shared feature worktree), and
   returns control.
2. Wait for `/varde-build` to report. Record the plan's start, done, or blocked
   outcome as one line in the feature run-state file
   (`memory-bank/working/plans/<group-id>/run-state.md`).
3. Move to the next child plan.

The orchestrator never dispatches tasks, edits source, or runs review itself —
all of that happens inside `/varde-build`.

## Fail-closed halting

If a child plan blocks or `/varde-build` reports a Failure State:

- Halt the feature run immediately. Do not build later plans.
- Leave the feature worktree as-is (completed plans' commits included, the
  failed plan's partial state included) for the human.
- Do not merge to the original branch.
- Report which child plan stopped and why, and note which plans completed.

## Final merge

Once every child plan's `status` is `completed`:

- **Feature base-branch invariant:** the original branch (real `HEAD`) is
  touched exactly once, here. Each child plan committed into the shared feature
  worktree; there was no per-plan merge to the original branch.
- Present the aggregate diff once and offer **Merge** or **Stop** as a
  two-option prompt — match the harness's native prompting style, falling back
  to a numbered inline menu where there is none.
- **Merge**: invoke `varde-worktree`: `merge id=orchestrate-<group-id>
  into=<original-branch>` — name the original branch explicitly. On a conflict,
  follow `varde-worktree`'s `references/RESOLVE.md` with intent "integrate
  feature <group-id>". After a successful Merge, `cleanup
  id=orchestrate-<group-id>` removes the worktree and branch. Optionally set the
  group `plan.md` `status: completed`.
- **Stop**: leaves the feature worktree committed but unmerged (do not `cleanup`
  on Stop — the run-state worktree anchor stays valid for a later Merge).
- Recommend Merge when all plans completed cleanly; recommend Stop when any plan
  surfaced warnings.

## Resume gate

Before resuming an interrupted feature run, first recover the feature worktree:
read the branch/path from the feature run-state file. If the branch exists
(`git show-ref --verify --quiet refs/heads/<name>`), reattach that worktree —
never create a second one. If the run-state file has no worktree line
(interrupted before step 3), treat this as a fresh start. If the branch is
missing despite a recorded name, stop and surface it — do not recreate under the
same name.

Then derive progress from child `plan.md` statuses: every `completed` child is
done (its commits are on the feature worktree branch) and is skipped; resume
building at the first non-`completed` child in dependency order. If a child is
`completed` but has no commits on the branch, or a non-terminal child has
partial commits, stop and surface it rather than inferring the outcome.

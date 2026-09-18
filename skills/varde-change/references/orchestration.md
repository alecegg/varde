# Feature Orchestration

Load this before orchestrating a feature. It covers resolving a group plan and
its children, ordering them, delegating each to `varde-change build`,
stop-on-failure halting, the final merge, and the resume check.

## Resolving the group

A feature is a **group plan** (`plan.md` frontmatter `shape: group`) created by
`varde-change plan`. Its child plans live in nested directories:

```
memory-bank/working/plans/<group-id>/<child-slug>/plan.md
```

Discover children by listing those directories and reading each `plan.md` —
membership is derived by nesting, never from a `children:` frontmatter field.
Each child's compound id is `<group-id>/<child-slug>`. Read each child's
`status`, `title`, and plan-level `depends_on`.

If the target is a non-group plan, do not orchestrate — invoke
`varde-change build plan=<id>` directly. Orchestration only earns its place
across two or more plans.

### No-argument discovery

List plan directories, keep those whose `plan.md` has `shape: group`, and among
those keep any with at least one child not yet `completed`. Present each as
`<group-id> — <title>` with the group's `goal` as description. If none, output
"No group plans with unbuilt children. Nothing to orchestrate." and stop.

## Ordering the children

Topologically sort the children by plan-level `depends_on` (each entry resolves
to a sibling child id or a compound id). Treat `completed` children as satisfied.
Report and skip any child whose `depends_on` names a plan that is neither a
discovered sibling nor `completed`. Treat a cycle as a hard failure.

Child plans are file-disjoint by split construction — the split drew boundaries
along subsystems — so ordering need only respect `depends_on`. There is no
cross-plan file-conflict resolution.

## Per-plan delegation

For each child plan not already `completed`, in dependency order, invoke
`varde-change build plan=<child-id>` with the selected feature location as its
effective `repoRoot`, wait for it to report, then move to the next.

Running inside the feature location means `varde-change build` defaults to that
checkout and does not isolate again — it runs the plan's tasks, completes the
plan, and commits there, skipping its own Merge/Stop because it does not own the
location.

The orchestrator never dispatches tasks, edits source, or runs review itself.

## Stop when a plan fails

If a child plan blocks or `varde-change build` reports a Failure State, halt the
feature run immediately. Do not build later plans, and do not merge. Leave the
feature location as-is — completed plans' commits and the failed plan's partial
state included — and report which child stopped, why, and which plans completed.

## Final merge

Once every child plan is `completed`:

- **Base-branch invariant:** the original branch is touched exactly once, here.
  Each child committed into the shared feature location; there was no per-plan
  merge.
- With no feature worktree, the source commits are already in the current
  checkout. Nothing to merge.
- Otherwise present the aggregate diff once and offer **Merge** or **Stop**.
  Merge follows `references/worktree.md`, naming the original branch explicitly,
  then cleans up the worktree and branch; optionally set the group `plan.md`
  `status: completed`. Stop leaves the feature worktree committed but unmerged —
  do not clean up on Stop, so a later Merge stays possible.
- Recommend Merge when all plans completed cleanly; recommend Stop when any plan
  surfaced warnings.

## Resume check

Recover the feature location first. If a feature branch exists
(`git show-ref --verify --quiet refs/heads/orchestrate-<group-id>`), reattach
that worktree rather than creating a second one. With no feature branch, resume
in the current checkout.

Then derive progress from child `plan.md` statuses: every `completed` child is
done and is skipped; resume at the first non-`completed` child in dependency
order. If a `completed` child has no commits, or a non-terminal child has partial
commits, stop and show it rather than inferring the outcome.

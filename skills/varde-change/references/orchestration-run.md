# Run a feature group

Load this only after a group is named or selected.

## Resolve the group

Read the selected group plan and its nested child plans:

```text
<working>/plans/<group-id>/<child-slug>/plan.md
```

Derive membership from directory nesting.
Never use a `children:` frontmatter list.
Read each child's `status`, `title`, and `depends_on`.
Use `<group-id>/<child-slug>` as its compound id.

If the selected plan lacks `shape: group`, invoke
`varde-change build plan=<id>` and stop.

## Choose the feature location

Run `git check-ignore -q` against the group plan.
Ignored plans run inside the current checkout.
Tracked plans use one feature worktree.
Load `references/worktree.md` before creating that worktree.
Use id `orchestrate-<group-id>`.
Treat its printed path as the effective `repoRoot`.

Reuse an existing `orchestrate-<group-id>` branch.
Never create a second feature location.

## Order children

Prefer `varde-workflow` when available:

```text
varde-workflow graph <group-id>/<child-slug>/plan.md --json
```

Pass a child plan, never the group plan.
Use returned nodes, edges, blockers, and schema.
Otherwise topologically sort plan-level `depends_on`.
Dependencies may name sibling ids or compound ids.
Treat completed dependencies as satisfied.
Skip children already marked `completed`.

Missing dependencies block their affected child.
A dependency cycle stops the entire feature.
Report the blocker before any child execution.

## Delegate children

Run remaining children sequentially in dependency order.
For each child, invoke:

```text
varde-change build plan=<compound-child-id>
```

Use the feature location as its effective `repoRoot`.
Wait for each build result before continuing.
Build owns all single-plan execution and review.
Build skips its own merge inside this location.
The orchestrator never dispatches tasks or edits source.

When a child blocks or fails, stop immediately.
Do not run later children. Do not merge anything.
Leave completed commits and partial state unchanged.
Report the failed child, reason, and completed children.

## Resume

Recover any existing feature location first.
Derive progress from current child statuses.
Resume at the first non-`completed` ordered child.

Stop when status and commits disagree.
Examples include completed children without commits.
Partial commits on non-terminal children also require review.

## Finish

After every child completes, offer one Merge or Stop.
With ignored plans, commits already exist locally.
No merge action is needed there.

For a feature worktree, show its aggregate diff once.
Merge into the explicitly named original branch.
Then remove the worktree and feature branch.
Stop preserves both for later resumption.
Optionally transition an active group to `completed`.

The original branch changes only during this final merge.
Recommend Merge after clean child completion.
Recommend Stop when child work produced warnings.

Finally invoke `varde-knowledge reflect` as a session boundary.
Child builds already recorded their nested lessons.
This reflection writes the feature-level handoff.

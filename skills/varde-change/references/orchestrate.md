# Orchestrate mode

## Where to start

| The request is | Start |
|---|---|
| A named group of plans to run | Run that group plan's children in dependency order. |
| An ask to build a whole feature, with no group named | Find group plans (`shape: group`) with unbuilt children, present them, then run the one selected. See `references/orchestration.md`. |
| A single plan that turns out not to be a group | Hand it to `varde-change build` — one plan needs no orchestration. |

## Workflow

This skill runs a **feature** — a group plan (`shape: group`) whose child plans
were created by `varde-change plan` after the plan was completed. It walks the children in
plan-level dependency order, **one at a time, sequentially, unattended**,
delegating each to `varde-change build`. Tracked storage gets one final merge.
Ignored storage runs locally without merging. It
adds no execution logic of its own — `varde-change build` owns everything
about running one plan. Child plans are file-disjoint by split construction, so
running them in order needs no conflict resolution.

1. **Load the reference.** Load `references/orchestration.md` (group resolution,
   dependency ordering, the per-plan delegation rules, stop-on-failure halting,
   and the resume check).

2. **Resolve the group.** If the named plan is not a group, invoke
   `varde-change build plan=<id>` and stop. Otherwise resolve the group plan
   (`shape: group`) and discover its nested child plans by directory nesting
   (`memory-bank/working/plans/<group-id>/<child-slug>/plan.md`) — not from any
   `children:` frontmatter. Full procedure: `references/orchestration.md`.

3. **Choose the feature location.** Run `git check-ignore -q` against the group
   plan. If tracked, create one isolated feature worktree per
   `references/worktree.md` with id `orchestrate-<group-id>`, and run every step
   below with the printed `path=`/`branch=` as the effective `repoRoot`. If
   ignored, keep the run in the current checkout so every plan stays available.

4. **Order the child plans.** Topologically sort the children by their
   plan-level `depends_on`; treat a dependency cycle as a hard failure. Full
   procedure: `references/orchestration.md`.

5. **Build each plan in order.** For each child plan not already `completed`,
   invoke `varde-change build plan=<child-id>` with the selected feature location
   as the effective `repoRoot` — `plan=<child-id>` is how this skill names which
   plan to build, and build reads nothing else to choose. Build does not own that
   location, so it skips its own merge, cleanup, and Merge/Stop; this file owns
   the final merge. Wait for it to report, then move to the next. If a plan
   blocks or fails, stop immediately, leave the feature location as-is, and
   report which plan stopped and why — do not merge or continue to later plans.
   Delegation rules: `references/orchestration.md`.

6. **Merge the feature.** Once every child plan is `completed`, offer Merge or
   Stop once for the feature worktree, then clean up `orchestrate-<group-id>` on
   Merge. With no worktree the source commits are already local and there is
   nothing to merge. Full procedure: `references/orchestration.md`.

7. **Record lessons.** Invoke `varde-knowledge reflect`, stating that this is a
   session boundary: the completed feature run is top-level, so reflection
   collects friction and useful knowledge and writes a handoff for the next
   session. Each child plan already recorded friction and knowledge through
   `varde-change build`; this is the one handoff for the whole feature.

## Gotchas

- A group plan (`shape: group`) has no tasks of its own; its children are
  discovered by directory nesting, never a frontmatter list. Read child status
  from each child `plan.md`'s frontmatter `status` (`completed` = built).
- `varde-change build` owns all single-plan execution (task decomposition, TDD,
  review, per-plan completion). Child plans carry a spec + plan-level acceptance
  criteria, not task files — build decomposes each when it runs. This skill never
  dispatches tasks or edits source itself.
- With a feature worktree, the original branch is touched once, at the final
  Merge. Otherwise each child commits directly in the current checkout.
- Resume derives progress from child `plan.md` statuses — `completed` plans are
  skipped. See `references/orchestration.md`.

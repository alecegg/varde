---
name: varde-orchestrate
description: >
  TRIGGER: Build a whole feature that spans multiple plans — a split/group plan
  and its child plans — end to end and unattended. Walk the child plans in
  dependency order, build each via /varde-build in one shared feature worktree,
  then do a single final merge. SKIP: Skip for a single plan (use /varde-build),
  and for planning, review, or refinement.
  Example phrases: "build this whole feature" or "run all the plans for this".
---

## Entry point dispatch

| Invocation | Action |
|---|---|
| *(no argument)* | Discover group plans (`shape: group`) with unbuilt children per `references/ORCHESTRATION.md`, present them, then orchestrate the selected one. |
| `group=<plan-id>` | Orchestrate that group plan's children in dependency order, unattended. |
| `plan=<plan-id>` (a non-group plan) | Cede directly to `/varde-build plan=<plan-id>` — a single plan needs no orchestration. |

## Workflow

This skill runs a **feature** — a group plan (`shape: group`) whose child plans
were created by `/varde-plan`'s post-spec split. It walks the children in
plan-level dependency order, **one at a time, sequentially, unattended**,
delegating each to `/varde-build`, and does a single final merge to the original
branch. It adds no execution logic of its own — `/varde-build` owns everything
about running one plan. Child plans are file-disjoint by split construction, so
running them in order needs no conflict resolution.

1. **Load the reference.** Load `references/ORCHESTRATION.md` (group resolution,
   dependency ordering, the per-plan delegation contract, fail-closed halting,
   and the resume gate).

2. **Resolve the group.** If given `plan=<id>` for a non-group plan, cede to
   `/varde-build plan=<id>` and stop. Otherwise resolve the group plan
   (`shape: group`) and discover its nested child plans by directory nesting
   (`memory-bank/working/plans/<group-id>/<child-slug>/plan.md`) — not from any
   `children:` frontmatter. Full procedure: `references/ORCHESTRATION.md`.

3. **Create the feature worktree.** The whole feature run lands in one isolated
   worktree; the original branch is touched exactly once, by this skill's final
   merge (feature base-branch invariant). Invoke `varde-worktree`:
   `create id=orchestrate-<group-id>`, and run every step below with the printed
   `path=`/`branch=` as the effective `repoRoot`/branch. Record the worktree
   branch/path in the feature run-state file
   (`memory-bank/working/plans/<group-id>/run-state.md`, creating it if absent) —
   the crash-recovery anchor a resumed run reads first
   (`references/ORCHESTRATION.md`'s Resume gate).

4. **Order the child plans.** Topologically sort the children by their
   plan-level `depends_on`; treat a dependency cycle as a hard failure. Full
   procedure: `references/ORCHESTRATION.md`.

5. **Build each plan in order.** For each child plan not already `completed`,
   invoke `/varde-build plan=<child-id>` with the feature worktree as the
   effective `repoRoot`. Because that runs inside this skill's worktree, if
   `/varde-build` isolates at all its `create` returns `created=false`, so it
   automatically skips its own merge/cleanup and Merge/Stop — this skill owns
   the single final merge (`varde-worktree`'s ownership rule). Wait for it to report,
   record the plan's start/done/blocked as one line in the feature run-state
   file, then move to the next. **Fail-closed:** if a plan blocks or fails, halt
   immediately, leave the feature worktree as-is, and report which plan stopped
   and why — do not merge, do not continue to later plans. Full delegation
   contract: `references/ORCHESTRATION.md`.

6. **Merge the feature.** Once every child plan is `completed`, offer Merge/Stop
   once: the single merge of the feature worktree branch (step 3) into the
   original branch, or Stop to leave it staged. Full procedure:
   `references/ORCHESTRATION.md`. On Merge, `cleanup id=orchestrate-<group-id>`.

7. **Reflect and consolidate.** Invoke `varde-reflect boundary`, if available —
   the completed feature run is a top-level session boundary, so it harvests
   friction and durable knowledge and writes a carry-forward handoff so the next
   session starts cheap. (Each child plan already reflected friction + knowledge
   via `varde-build`'s nested close; this is the one handoff for the whole
   feature.) If `varde-reflect` isn't installed, fall back to `varde-friction`
   scoped to this skill's own execution.

## Gotchas

- A group plan (`shape: group`) has no tasks of its own; its children are
  discovered by directory nesting, never a frontmatter list. Read child status
  from each child `plan.md`'s frontmatter `status` (`completed` = built).
- `/varde-build` owns all single-plan execution (task decomposition, TDD,
  review, per-plan completion). Child plans carry a spec + plan-level acceptance
  criteria, not task files — build decomposes each when it runs. This skill never
  dispatches tasks or edits source itself.
- Base-branch invariant: the original branch (real `HEAD`) is touched exactly
  once per feature run, at step 6's Merge/Stop. Each child plan commits into the
  shared feature worktree; there is no per-plan merge to the original branch.
- Resume derives progress from child `plan.md` statuses (`completed` plans are
  skipped) plus the run-state worktree anchor — see `references/ORCHESTRATION.md`.

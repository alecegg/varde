# Finish a built plan

Finish only after every task is done.

1. Run one report-only `varde-review report` pass. Provide the plan goal,
   acceptance criteria, completed tasks, and verification evidence.
2. When findings exist, run one `varde-review fix mode=build` round. Pass the
   review ID and `plan_context`. Attempt every finding. Report remaining items
   as deferred. Do not re-review.
3. Stop completion when companion plans remain.
4. Execute every acceptance criterion's assert or retrieve check. Inspect
   retrieved evidence. Check only confirmed criteria. Any unconfirmed criterion
   blocks completion.
5. Refresh each `observed_specs` domain through `varde-docs spec`.
6. Run `varde-workflow conclude <plan.md> --json`. Preserve its journal and
   recover before retrying failures. Without this CLI, stop before conclusion
   mutations.
7. Run `varde-knowledge reflect`. Record friction, knowledge, and the top-level
   completion handoff. Record outcomes through
   `varde-workflow conclusion-action`.

Show the completed local diff in place.
If this run created a worktree, offer Merge or Stop.
Read `references/build-interview.md` and `references/worktree.md` then.
Default to Merge. Stop preserves the committed worktree.

Archive terminal plans only when the repository uses that convention.
Commit tracked plan moves.

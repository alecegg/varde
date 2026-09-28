# Parallel wave

Load only when `references/build-dispatch.md` selects the `parallel` strategy.
Load `references/worktree.md` for binding authorization and release.

## Run the wave

1. Start with a clean target checkout and this wave's bookkeeping committed.
   Record the checked-out branch and its starting SHA. For each task, run
   `scripts/worktree-create.sh <task-id> <recorded-sha>`. If any call reports
   `created=false`, run the tasks serially instead.
2. Register each task worktree against its parent subject using the task
   ownership and original task path, per `references/worktree.md`. Pass the
   returned binding context with the task briefing. Dispatch each executor
   into its task worktree with the task briefing,
   `#### Verification` checks, declared ownership, and bounded context. Give
   it the task file's absolute path in the main checkout for reference only,
   plus the resolved absolute `<working>` and `<knowledge>` paths. Workers use
   those paths without re-resolving them.
   Workers edit their scope, run their checks, commit on their branch, and
   report `done`/`blocked`, evidence, commit, owned paths, and worktree path.
   Workers do not edit task files.
3. Collect every result before integrating. Apply `build-dispatch.md`'s
   ownership check to each worker's task commit; a stray path makes that
   worker failed, with the stray path list sent on the one corrective retry.
   If any worker fails or blocks,
   leave the target branch untouched and retain all worker refs. Do not merge
   successful workers from that wave. Diagnose the failure first; successful
   independent work can be selected as a later smaller wave.
4. Once every worker passes, create an integration worktree at the recorded
   target SHA with `scripts/worktree-create.sh <wave-id>-integration <target-sha>`.
   From that integration worktree, merge each worker in
   task-id order with `scripts/worktree-merge.sh <task-id>`. Do not clean up
   worker worktrees yet. On a merge failure, keep the target unchanged and
   retain the worker and integration refs for diagnosis.
5. Run the combined wave verification in the integration worktree. On any
   failure, keep the target unchanged and retain the worker and integration
   refs. Do not clean up.
6. Capture each worker's binding evidence from the approval checkout before
   advancing the target. The integration worktree holds source merges and checks
   only; do not transition or edit task files there.
7. Return to the original target checkout. Confirm it is still on the recorded
   branch at the recorded SHA and is clean. Advance it once with
   `git merge --ff-only worktree/<wave-id>-integration`. This fast-forward is
   the only operation that changes the target ref for the source wave. If it
   cannot fast-forward, keep all recovery refs and diagnose before retrying.
8. From the approval checkout, inspect and release every worker binding against
   its integrated commit. Then update each task's transition and Progress
   evidence from worker reports; commit tracked task bookkeeping separately.
   External task files follow the same parent-owned sequence. A bookkeeping or
   release failure leaves the verified source integrated: retain recovery refs,
   report the exact pending step, and resume it without re-merging the wave.
   Clean up worker and integration worktrees only after all releases and
   bookkeeping succeed.

On resume, confirm each recorded worker and integration branch and path still
exist before reusing it; a missing recovery worktree is a blocker, not
something to recreate. A failed worker, merge, or combined verification must
leave the target SHA unchanged. Keep recovery refs until the failure is
diagnosed.

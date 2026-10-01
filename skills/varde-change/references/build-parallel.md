# Parallel wave

Load `references/build-worktree.md` for worktree binding authorization and release.

## Shared-checkout wave

1. The orchestrator waits for every executor, then confirms each changed path
   belongs to exactly one task and each reported hash still matches.
2. Run combined verification for the wave, including rerunning checks reported
   as `waiting: sibling failure`. If ownership, hashes or verification fail,
   commit nothing and keep the tree for diagnosis.
3. Once all checks pass, commit each task's owned paths in its own commit,
   then commit bookkeeping separately.

## Worktree wave

A failed worker, merge, or combined verification leaves the target SHA
unchanged; keep every worker and integration ref until the failure is
diagnosed.

## 1. Create worker worktrees

1. Start from a clean target checkout with this wave's bookkeeping committed.
2. Record its branch and starting SHA.
3. Per task, run `scripts/worktree-create.sh <task-id> <recorded-sha>`. If any
   call reports `created=false`, run the tasks serially instead.

## 2. Dispatch workers

1. Register each task worktree against the parent subject with the task
   ownership and original task path, per `references/build-worktree.md`.
2. Dispatch each executor into its worktree with the `build.md` brief
   plus:
   - the returned binding context;
   - the task file's absolute path in the main checkout, for reference only.
3. Workers edit their scope, run their checks, and commit on their branch
   without editing task files. Each reports:
   - `done`/`blocked`
   - evidence
   - commit
   - owned paths
   - worktree path

## 3. Collect results

1. Collect every result before integrating.
2. Run `scripts/check-task-ownership.py` per `build.md` on each task commit as
   an early check; release already rejects committed scope escapes. A stray
   path fails that worker; its path list goes with the one corrective retry.
3. If any worker fails or blocks, merge none of that wave. Diagnose first, then
   run successful independent work as a later, smaller wave.

## 4. Integrate and verify

1. Create an integration worktree at the recorded SHA:
   `scripts/worktree-create.sh <wave-id>-integration <target-sha>`.
2. From it, merge each worker in task-id order with
   `scripts/worktree-merge.sh <task-id>`.
3. Run the combined wave verification there.

The integration worktree holds source merges and checks only; never transition
or edit task files there.

## 5. Advance the target

1. Capture each worker's binding evidence from the approval checkout.
2. Confirm the original target checkout is clean, on the recorded branch, at
   the recorded SHA.
3. Run `git merge --ff-only worktree/<wave-id>-integration`, the only operation
   that changes the target ref for the wave. If it cannot fast-forward,
   diagnose before retrying.

## 6. Release and record

1. From the approval checkout, inspect and release every worker binding
   against its integrated commit.
2. Record each task's transition and Progress evidence from worker reports,
   including external task files.
3. Commit tracked task bookkeeping separately.
4. Clean up worker and integration worktrees only after all releases and
   bookkeeping succeed.

A bookkeeping or release failure leaves the verified source integrated: keep
recovery refs, report the exact pending step, and resume it without
re-merging the wave.

## Resume

Confirm each recorded worker and integration branch and path still exists
before reusing it. A missing recovery worktree is a blocker, not something to
recreate.

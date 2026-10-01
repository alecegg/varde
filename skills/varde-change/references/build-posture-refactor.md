# Refactor Posture

Restructure code without changing observable behavior: for the same inputs, the
same stdout, stderr, return code, side effects, and test results. Public APIs,
error messages, log output, and wire formats stay unchanged.

Reuse an unchanged approved plan verdict supplied by the caller.
For a bounded refactor without a task file, use its contract scope and a stable
change ID wherever this posture names task scope or ID.

## Bootstrap

1. Use `varde-knowledge` to find pattern notes matching the target paths or
   names, and read only those.
2. Select the explicit target, else the task's review findings (confirm each
   still applies) or structural goal; if none, ask.
3. Record the target branch and SHA. Check selected paths with
   `git status --short -- <selected-paths>` and inspect their diffs; keep
   uncommitted edits in the original checkout. If a dirty target path must be
   refactored, stop until its current content is committed to the target branch.
4. If `git diff --cached --quiet` fails because other work is staged, create
   or reuse a dedicated worktree with
   `scripts/worktree-create.sh <task-id>-refactor <target-sha>` and work only
   in its printed `path=` (`created=true` means you own its later merge and
   cleanup; `created=false` means the caller does). The worktree excludes
   uncommitted edits, which stay untouched in the original checkout. On
   resume, confirm the recorded branch and path before reuse. Otherwise, work
   in the current checkout.
5. When the printed path differs from the subject's approval checkout, load
   `references/build-worktree.md`, bind its approved scope before editing, and use
   that binding context for start/resume checks. Any task file is reference
   material; return evidence for parent-owned state updates.
6. Find each target file's covering tests (`tests_for_file`, naming convention,
   or grep for test-directory imports) and read them in full. If none exist,
   write a characterization test pinning current behavior before any
   structural edit. Block only when the target cannot be exercised at all.

## Cadence

1. Run the full suite or scoped subset in the working location; record
   pre-existing failures.
2. For each attempt, record its paths, make one change, and verify it. Start
   with no unstaged changes in the attempt's paths; do not stage an attempt
   before it passes.
3. On regression, restore only that attempt: run
   `git restore --worktree -- <tracked-attempt-paths>` to return tracked files
   to the last verified index checkpoint, then remove only attempt-created
   untracked paths by their explicit names. Never run whole-tree `git clean`,
   `git checkout`, or reset commands.
4. After an attempt passes, stage its verified paths as a checkpoint. Later
   rollback must preserve those staged steps.
5. Before inlining a function, count its real callers (`varde-code dependents`
   or grep); more than one means it is not an inline target.
6. Rename only when the rename is the change, never as a side effect of
   another one.
7. Outside a parallel wave, commit verified source paths once: for a task,
   per `build-execution.md` Completion step 4; without one, with the bounded
   change ID in the message and no task bookkeeping.

## Verify

Verify with the independently approved checks and any task
`#### Verification` asserts, adding broad checks only when consumers, shared
behavior, or coverage uncertainty justify them. Record how the checks
establish behavior preservation.

## Integrate

Run this section only when you used a dedicated worktree.

- **You own the worktree:** return to the target checkout and confirm its
  branch and SHA are unchanged. If the merge would overwrite one of its
  uncommitted edits, keep the worktree and branch and stop. Otherwise run
  `scripts/worktree-merge.sh <task-id>-refactor`, inspect and release its
  binding against the integrated source commit, then run
  `scripts/worktree-cleanup.sh <task-id>-refactor`.
- **The caller owns it:** report the commit and return pending state with its
  binding; merge and cleanup belong to that owner.

For a task, the parent updates its files and marks it done only after its
source commit is integrated and its binding released; during a parallel wave,
the orchestrator handles that during its wave-merge.
Without a task, run the bounded route's complete review checkpoint after
integration and binding release.

## Summary

End with a `File | Change | Verification` table, or "No behavior-preserving
changes found."

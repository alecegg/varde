# Refactor Posture

Restructure code without changing observable behavior: for the same inputs, the
same stdout, stderr, return code, side effects, and test results. Public APIs,
error messages, log output, and wire formats stay unchanged.

Apply `references/review-gates.md` before implementation edits and at
completion. Reuse an unchanged approved plan verdict supplied by the caller.

## Bootstrap

1. Read `<knowledge>/pattern/` if it exists.
2. Select the explicit target (path, glob, or free-text direction), else the
   review findings the task addresses (confirm each still applies at its
   listed location), else the task's structural goal. If none is given, ask.
3. Record the target branch and SHA. Inspect its status and diffs for the
   selected paths before creating a worktree. A new worktree excludes
   uncommitted edits. Leave those edits untouched in the original checkout;
   if a dirty target path must be refactored, stop before editing it and resume
   only after its current content is included in the target branch's commit.
4. Create or reuse a dedicated worktree with
   `scripts/worktree-create.sh <task-id>-refactor <target-sha>`. If there is no
   task file, use a stable short change ID in place of `<task-id>`. Work only
   in the printed `path=`. `created=true` means you own the worktree and later
   merge and clean it up; `created=false` means the caller owns those actions.
   On resume, confirm the recorded branch and path before reuse.
   When the printed path differs from the subject's approval checkout, load
   `references/worktree.md`, bind its approved task scope before editing, and
   use that binding context for start/resume checks. The original task file is
   reference material; return evidence for parent-owned state updates.
5. Find each target file's covering tests (`tests_for_file`, naming convention,
   or grep for test-directory imports) and read them in full. If none exist,
   write a characterization test pinning current behavior before any
   structural edit. Block only when the target cannot be exercised at all.

## Cadence

1. Run the full suite or scoped subset in the worktree; record pre-existing
   failures.
2. For each attempt, record its paths, make one change, and verify it. Start
   with no unstaged changes; do not stage an attempt before it passes.
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
7. Outside a parallel wave, follow `build-execution.md` Completion step 5 and
   commit the task's source paths once, excluding task bookkeeping in an isolated worker. If you
   own the worktree, return to the target checkout and confirm its branch and
   SHA are unchanged. Preserve its uncommitted edits; if the merge would
   overwrite one, keep the worktree and branch and stop. Otherwise run
   `scripts/worktree-merge.sh <task-id>-refactor`, inspect and release its
   binding against the integrated task commit, then clean it up with
   `scripts/worktree-cleanup.sh <task-id>-refactor`. If the caller owns the
   worktree, report the commit and leave merge and cleanup to that owner.
   The parent updates all tracked or external task files only after integration
   and release. A caller-owned worktree returns pending state with its binding.
   During a parallel wave, leave task files to the orchestrator per
   `references/build-parallel.md`. For a non-parallel isolated refactor, mark its task done only after the
   worktree owner has merged the task commit successfully.

Verify with the independently approved checks and the task's
`#### Verification` asserts. Include broad checks when affected consumers,
shared behavior, or unresolved coverage uncertainty justify them. Complete
required repository checks; do not repeat the full suite after each task
without new failures, changes, or coverage concerns. Record how the checks
establish behavior preservation.

## Summary

End with a `File | Change | Verification` table, or "No behavior-preserving
changes found."

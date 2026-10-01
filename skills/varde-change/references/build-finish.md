# Finish a built plan

When this run owns an isolated checkout or is a caller-owned feature child,
follow `references/build-worktree.md` (Finish an isolated run) first; otherwise,
enter finish after every task is done and nested children are completed.

## 1. Finish edits and checks

Finish all source and documentation edits before the final implementation
review:

1. Update a module changelog when it exists.
2. When `plan.md` lists `observed_specs`, refresh the touched domains through
   `varde-docs spec`; conclusion rejects stale specifications.
3. Run `varde-review simplify`, scoped to the whole plan diff, only when
   `git diff --shortstat` shows the plan diff over 150 changed lines or the
   diff adds new files or abstractions; then rerun the affected checks.
4. Run every acceptance-criteria assert/retrieve check.

## 2. Review the implementation

Review the completed change and record the risk decision per
`references/review-gates.md`; choose the reviewer per
`references/review-gates.md` §5. Implementation review is always required;
dispatch the selected reviewer for one report-only pass with:

- plan id;
- subject id;
- goal;
- acceptance criteria;
- completed tasks and verification evidence;
- the execution location (checkout or worktree path);
- the parent's resolved absolute `<working>` and `<knowledge>` paths.

Tell the reviewer to use those paths without re-resolving. Then ask the
reviewer to:

- inspect phase `implementation`;
- record full-subject evidence through `varde-workflow review record`.

If an independent reviewer is unavailable, leave required review pending.
Commit a report folder if one is written and plan storage is tracked.

## 3. Fix findings

- **Agent-document findings:** apply an independently approved bounded
  `varde-change` change and record it in plan Progress; no review folder.
- **Code findings:** when at least one finding is eligible (`varde-review`
  fix.md, Review-folder routes), dispatch one `executor` round of
  `varde-review fix mode=build` with `repoRoot`, the review folder, `plan_context`, and the
  parent's resolved absolute `<working>` and `<knowledge>` paths; the executor
  uses them without re-resolving. For an independent review folder, dispatch it with
  `mode=standalone`, `review_dir`, and `repoRoot`, without `plan_context`.
  With none eligible, go straight to triage.

The parent receives deferred findings, presents one triage table in fix.md's
format, and records the user's choices:

- **Fix:** a bounded `varde-change build` task with its ID in `finding_ids`,
  its concrete approved solution, and traceable user decision evidence, per
  `varde-review fix` Parent workflow; the executor touches only those IDs.
- **Dismissal:** the parent records its reason.
- **Action-item:** the parent creates a nested companion plan.

Under orchestrate, return unresolved findings instead of pausing.

## 4. Confirm acceptance criteria

After fixes, rerun the affected assert or retrieve checks. Inspect retrieved
evidence. Check only confirmed criteria; any unconfirmed criterion blocks
completion.

## 5. Escalate deferred findings

Before `conclude`, run `scripts/escalate-deferred.py --plan-dir <plan-dir>
--deferred-dir <working>/reviews/deferred` (absolute paths; safe to rerun) and
report its lines; on exit 1, fix the reported finding and rerun.

## 6. Conclude

1. Run the complete check and resolve every reported blocker; never conclude
   from a stale or missing record:

   ```sh
   varde-workflow review check --subject <subject-id> --checkpoint complete --json
   ```

2. Move the plan to `completed` with `varde-workflow conclude <plan.md>
   --json`. On failure, preserve its journal and recover before retrying.
   After `conclude`, check post-conclusion actions with `conclusion-status`;
   reset failed ones with `conclusion-retry`.
3. Commit the plan's status change when plan storage is tracked.

## 7. Record lessons

Run this step only when the build hit obstacles or made durable decisions:

- Record real obstacles through `varde-learn` and durable decisions through
  `varde-knowledge`.
- At a top-level boundary, run `varde-knowledge reflect` for durable notes and
  a handoff; a run nested inside the varde-change orchestrator writes no
  handoff.

With the CLI, record each outcome through `varde-workflow conclusion-action`;
a skipped action gets `--output "none: no obstacles or decisions"`.

## Finish choices

Show the local diff and the current branch/worktree state. Under `varde-change
orchestrate`, return those facts without offering or executing a choice; the
orchestrator presents one after all children complete. Otherwise offer the
applicable choices, recommending Merge for a worktree this run created and
Keep as is in the user's checkout:

- **Merge:** for a varde-created worktree owned by this run (`created=true`),
  run `scripts/worktree-merge.sh <id>` and, only after success,
  `scripts/worktree-cleanup.sh <id>` per `references/build-worktree.md`. For a
  manually created branch, confirm its destination branch and merge there;
  never merge or clean up a caller-owned worktree (`created=false`). Merge is
  inapplicable in the current checkout with no separate branch; a detached
  HEAD needs a named branch first.
- **Push and open PR** (hidden when `gh` is unavailable): only after this
  explicit choice, require a clean committed branch and identify the intended
  base and remote. Create a named branch first when on detached HEAD or a
  default branch, push it, then run `gh pr create` with that base and head.
  Keep the branch/worktree for further PR work.
- **Keep as is.**

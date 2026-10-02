# Finish a built plan

Enter finish after every task is done and nested children are completed.

- **Isolated checkout (owned by this run, or a caller-owned feature child):**
  follow [Finish an isolated run](#finish-an-isolated-run) below.
- **Otherwise:** start at step 1.

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
5. Commit these edits by path, preserving unrelated edits.

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
- **Code findings:** first confirm the review folder and its required
  finding fields (`varde-review` fix.md, Select the review), skipping its tree
  check; unrelated edits never stop a plan finish. When at least one finding
  is eligible (`varde-review` fix.md, Review-folder routes), dispatch one
  `executor` round of `varde-review fix mode=build` with `repoRoot`, the
  review folder, `plan_context`, and the parent's resolved absolute
  `<working>` and `<knowledge>` paths; the executor uses them without
  re-resolving and enters through `varde-review`'s fix-pass.md (executor
  role; no further dispatch, no triage).
  With none eligible, go straight to triage. A fresh report leaves every
  `Disposition` blank, so its findings go to triage; the automated pass
  applies only findings already marked `fix`.

The parent receives deferred findings, presents one triage table in fix.md's
format, and records the user's choices:

- **Fix:** a bounded `varde-change build` task with its ID in `finding_ids`,
  its concrete approved solution, and traceable user decision evidence, per
  `varde-review fix` Parent workflow; the executor touches only those IDs.
- **Dismissal:** the parent records its reason.
- **Action-item:** the parent creates a nested companion plan.

Under orchestrate, return unresolved findings instead of pausing.

Commit each applied code or agent-document fix's paths before step 4.

## 4. Confirm acceptance criteria

After fixes, rerun the affected assert or retrieve checks. Inspect retrieved
evidence. Check only confirmed criteria; any unconfirmed criterion blocks
completion.

If step 3 changed any file, get refreshed implementation evidence before
step 6: the re-review may cover only the fixes, but its record covers the
entire subject change at the current fingerprint.

## 5. Escalate deferred findings

Before `conclude`, run `varde-workflow escalate-deferred --plan-dir <plan-dir>
--deferred-dir <working>/reviews/deferred` (absolute paths; safe to rerun) and
report its lines. Fix malformed findings before retrying; recover an interrupted
transaction with `varde-workflow recover` before rerunning.

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

Do this work only when the build hit obstacles or made durable decisions:

- Record real obstacles through `varde-learn` and durable decisions through
  `varde-knowledge`.
- At a top-level boundary, run `varde-knowledge reflect` for durable notes and
  a handoff; a run nested inside the varde-change orchestrator writes no
  handoff.

Always record all three actions (`reflection`, `friction`, `handoff`), one
call each; `conclude` leaves them pending:

```sh
varde-workflow conclusion-action <plan.md> <reflection|friction|handoff> [--output "<text>"] --json
```

A skipped action gets `--output "none: <reason>"`, such as `none: no
obstacles or decisions`.

## 8. Offer finish choices

Unless an isolated run already chose or merged under
[Finish an isolated run](#finish-an-isolated-run), offer them per `## Finish choices` below; under `varde-change orchestrate`, return
facts only.

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

## Finish an isolated run

An isolated run may enter at integration choice once source and checks are
verified and only post-integration parent bookkeeping remains. After
Merge/release, all tasks and nested children must be complete before final
review or conclusion.

When this run owns an unmerged isolated checkout, present applicable finish
choices before parent review or conclusion:

- **Merge:**
  1. Integrate verified source.
  2. Release bindings and apply parent-owned task bookkeeping.
  3. Continue at step 1 above, at the approval checkout.
- **Keep as is** or **Push and open PR:** follow Release in
  `references/build-worktree.md`.

A caller-owned feature child:

- **Subject in another approval checkout:** return pending integration to its
  owner without a merge choice.
- **Subject in the feature checkout:** conclude locally through its normal
  gates; leave the enclosing merge to the feature owner.

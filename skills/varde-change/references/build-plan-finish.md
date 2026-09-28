# Finish a built plan

Normally enter finish after every task is done and nested children are
completed. An isolated run may enter the integration-choice step when all task
source/checks are verified and the only pending task state is parent bookkeeping
after integration. After Merge/release, require every task done and every child
completed before final review or conclusion.

When this run owns an unmerged isolated checkout, present the applicable
finish choices before parent final review/conclusion. Merge integrates verified
source, releases its bindings and applies parent-owned task bookkeeping per
`references/worktree.md`; then continue below at the approval checkout. Keep as
is or Push and open PR retains the location and live bindings: report verified
source with parent completion pending, and write a handoff. Do not conclude a
parent against an unchanged source checkout. A caller-owned feature child whose subject belongs to another approval
checkout returns pending integration to that owner without its own merge choice.
A child whose subject belongs to the feature checkout instead concludes locally
through that checkout's normal gates, leaving the enclosing merge to the feature
owner; it does not borrow another checkout's identity.

1. Finish all source and documentation edits, update a module changelog when
   it exists, refresh every touched `observed_specs` domain through
   `varde-docs spec`, and run every acceptance-criteria assert/retrieve check.
   Complete these changes and checks before the final implementation review;
   conclusion rejects stale specifications.
2. Apply `references/review-gates.md` to the completed change. Record the risk
   decision; when independent implementation review is required, dispatch an
   independent agent for one report-only pass with the plan id, subject id,
   goal, acceptance criteria, completed tasks, verification evidence, the
   execution location (checkout or worktree path), and the parent's resolved
   absolute `<working>` and `<knowledge>` paths. Tell the reviewer to use those
   paths without re-resolving them. The reviewer inspects phase `implementation`
   and writes the full-subject evidence record directly through
   `varde-workflow review record`; do not substitute a report file or coordinator
   approval. Use `varde-agent-doc-authoring` for agent documents and
   `varde-review report` for code. Without an independent agent, leave required
   review pending. Commit a report folder when one is written and plan storage
   is tracked.
3. For agent-document findings, apply an independently approved bounded
   `varde-change` change and record verdict and evidence in plan Progress;
   `varde-agent-doc-authoring` findings need no invented review folder.
   For code findings, dispatch one `executor` round of
   `varde-review fix mode=build` with
   `repoRoot`, the review folder, `plan_context`, and the parent's resolved
   absolute `<working>` and `<knowledge>` paths; the executor uses them without re-resolving. That round commits its code edits once at round end
   (`varde-review fix`, Closing). The executor does not prompt for user triage
   or create companion plans. The parent receives deferred findings, presents
   one triage table in fix.md's format, and records the user's choices. A
   chosen fix becomes a bounded `varde-change build` task with its ID in
   `finding_ids`, its concrete approved solution, and traceable user decision
   evidence, per `varde-review fix` Follow-up contract; the executor touches
   only those selected IDs. A dismissal
   gets its reason recorded by the parent; an action-item becomes a nested
   companion plan created by the parent. Under orchestrate, return unresolved
   findings instead of pausing. For an independent review folder, the parent
   dispatches the executor with `mode=standalone`, `review_dir`, and `repoRoot`,
   without `plan_context`; user triage remains parent-owned there as well.
   Apply the pre-edit gate to fix plans. Any fix that changes covered files
   invalidates the final evidence fingerprint: rerun affected checks and obtain
   a fresh full-subject implementation record before completion.
4. Execute every acceptance criterion's assert or retrieve check after fixes.
   Inspect retrieved evidence. Check only confirmed criteria. Any unconfirmed
   criterion blocks completion.
5. Before `conclude`, scan this plan's nested review category files for findings
   with blank `Disposition` and an `Escalated:` note. Copy each complete finding
   block into the matching category file in the standing review
   `<working>/reviews/deferred/`; create/update its `review.md` in the normal
   review format. Give the copy the next unused
   category-local ID, keep `Disposition: blank` and `Escalated:`, and add
   `**Source:** <plan-id>/<review-id>` and `**Source finding:** <original-id>`.
   Check for an existing copy with that source and ID before appending, so
   retry is safe.
   Only after the copy is on disk, set the source finding's
   `Disposition: escalated`. These copies are visible follow-up work and do not
   block this plan's completion.
6. Run the final review check:

   ```sh
   varde-workflow review check --subject <subject-id> --checkpoint complete --json
   ```

   Resolve every reported blocker; do not conclude from a stale or missing
   record. Then move the plan to `completed` with
   `varde-workflow conclude <plan.md> --json`; preserve its journal and recover
   before retrying failures.
7. Record real obstacles through `varde-learn` and durable decisions through
   `varde-knowledge`. At a top-level boundary, run `varde-knowledge reflect`
   for durable notes and a handoff; a run nested inside
   `varde-change orchestrate` writes no handoff. With the CLI, record outcomes
   through `varde-workflow conclusion-action`.

Show the local diff and the current branch/worktree state. When called by
`varde-change orchestrate`, return those facts to the orchestrator without
offering or executing a finish choice; it presents one choice after all
children complete. Otherwise, offer the applicable finish choices: **Merge**,
**Push and open PR**, or **Keep as is**.
Recommend Merge for a worktree this run created, and Keep as is when already
in the user's checkout. Hide Push and open PR when `gh` is unavailable.

- Merge: for a varde-created worktree owned by this run (`created=true`), use
  `scripts/worktree-merge.sh <id>` and, only after success, `scripts/worktree-cleanup.sh <id>`
  per `references/worktree.md`. For a manually created branch, confirm its
  destination branch and merge there; never merge or clean up a caller-owned
  worktree (`created=false`). In the current checkout with no separate branch,
  Merge is inapplicable. A detached HEAD needs a named branch before merging.
- Push and open PR: only after this explicit choice, require a clean committed
  branch, identify the intended base and remote, create a named branch first
  when on detached HEAD or a default branch, push it, then use `gh pr create`
  with that base and head. Keep the branch/worktree for further PR work.
- Keep as is: leave the checkout, branch, and worktree in place.

Commit the plan's status change when plan storage is tracked.

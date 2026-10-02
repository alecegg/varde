# Automated fix pass

Process findings in category and file order, and return each non-applied
finding that needs a decision to the parent by identifier, with the reason
and any `Escalated:` note. Check eligibility before doing
any per-finding work (loading the block, validating its location, the plan
gate, or backups):

| Route | Eligible for automated application | Other dispositions |
|---|---|---|
| Standalone (`mode=standalone`) | Only supplied `finding_ids` with `Disposition: fix` and decision evidence | Skip `dismiss`, `action-item`, and `escalated`; return other non-eligible findings that need a decision to the parent. |
| Plan build (`mode=build`) | Any label with `Disposition: fix` | Send blank findings to parent triage without applying them; skip `dismiss`, `action-item`, and `escalated`. |

For a selected bounded fix, process only the supplied `finding_ids`; other
findings remain untouched. Each selected ID needs its concrete approved
solution and traceable user decision evidence; missing or mismatched evidence
returns that finding to the parent before editing. Preserve recorded decision
history on every defer/rejection; never infer approval from disposition alone.

## Per finding

For each eligible finding:

1. Load the complete finding block and confirm its location still matches:
   a local file, a CI check URL (re-read the check result and logs), or a
   review-relative screenshot (inspect it and trace the owning UI source).
2. For a selected bounded fix, use its concrete approved solution without
   substituting another. Otherwise pick the most reliable listed solution
   (mirrors a nearby pattern, touches the fewest files); if none is reliable,
   treat it as rejected in step 3.
3. In build mode, run the gate below. On rejection, relabel `triage` and
   leave `Disposition:` blank. Add one `**Escalated:**` value after
   `Location`, then move on:
   - `spec-conflict — <reason>`
   - `scope-creep — <reason>`
   - `human-only — <category>`
4. Run `scripts/snapshot.sh save <backup-dir>/<finding-id> <file>...` under a
   per-run `$TMPDIR` directory for every file the fix will touch or create.
   Avoid `git stash`/`git checkout`, which would discard earlier fixes.
5. Apply only the selected solution. For a screenshot finding, repeat its
   recorded route, viewport/device, and action; save and inspect an after
   screenshot beside the before image and record it in the finding; then
   recheck nearby layout or interaction that could regress. If the state cannot
   be reproduced or captured, leave the finding unresolved; tests alone do not
   establish visual verification.

## Verify the batch

1. Run the type check and tests once per package the batch touched (full repo
   when a fix spans packages). For a CI URL, run the failing check's local
   equivalent once.
2. In build mode, rerun the `assert:` lines of plan tasks (from
   `plan_context`) whose `modifies`/`creates` cover a fixed file.
3. On failure, restore the latest applied finding with `scripts/snapshot.sh
   restore <backup-dir>/<finding-id>`, rerun, and repeat until the checks pass.
   When several were restored, reapply each alone and keep it if checks pass.
   Restored findings keep a blank disposition (`reverted`).
4. For each remaining fix, confirm the defect is gone before `Disposition:
   fix`: prefer a check that failed before the fix (an existing test or step
   2's `assert:` lines); one passing before and after proves nothing. With
   none, re-read the path against `Summary` and record "confirmed by
   inspection".

## Commit

- In build mode, commit the round's applied fixes once at round end, staging
  only their paths; leave unrelated edits unstaged.
- For a PR source, commit only the verified fixes' paths on the local PR
  branch. Pushing, replying to, or resolving threads each need the user's
  explicit choice; the Executor never does them.

## When to defer to the user (under a build)

Check against `plan_context` (goal, plan-level criteria,
`creates`/`modifies`):

- **Spec conflict:** would the fix require the code to stop satisfying a
  plan-level acceptance criterion, or contradict something the plan explicitly
  specifies?
- **Scope creep:** would the fix change or break functionality outside the
  task's `creates`/`modifies` files, or introduce behavior the plan does not
  call for?
- **Human-only:** for report-categories' always-triage list
  (`references/report-categories.md`), require the selected finding ID,
  concrete approved solution, and traceable user decision evidence in the
  bounded build. Matching approval satisfies this category-only gate;
  missing or mismatched evidence escalates as `human-only — <category>`.
  Approval never bypasses spec-conflict, scope, ownership, independent review,
  or verification checks.

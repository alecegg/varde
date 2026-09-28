# Automated fix pass

Process findings in category and file order. Check eligibility before doing
any per-finding work, including loading the complete block, validating its
location, applying the plan gate, or backing up files:

| Route | Eligible for automated application | Other dispositions |
|---|---|---|
| Standalone (`mode=standalone`) | `Label: auto-fix` with `Disposition: blank` or `fix` | Skip `dismiss`, `action-item`, and `escalated`; return other non-eligible findings that need a decision to the parent. |
| Plan build (`mode=build`) | Any label with `Disposition: fix` | Send blank findings to parent triage without applying them; skip `dismiss`, `action-item`, and `escalated`. |

Do not apply a blank plan-build finding automatically. A build-mode finding
that the escalation gate changes to blank is also returned to the parent for
triage during that run.

For a selected bounded fix, process only the supplied `finding_ids`; other
findings remain untouched. Require the concrete approved solution and traceable
user decision evidence for each selected ID. Missing or mismatched evidence
returns that finding to the parent before editing. Preserve recorded decision
history on every defer/rejection; never infer approval from disposition alone.

For each eligible finding:

1. Load the complete finding block.
2. Verify every local file location exists and still matches the recorded
   location. For a CI finding located at a check URL, re-read the linked check
   result and logs instead of treating the URL as a file. For a visual finding
   located at a review-relative screenshot, inspect that image and trace the
   affected UI source before editing.
3. For a selected bounded fix, use its concrete approved solution without
   substituting another. Otherwise select the most reliable listed solution:
   the one that mirrors a nearby pattern and touches the fewest files. If none is reliable,
   send the finding to the human pass as in step 4 rather than inventing one.
4. In build mode, run the gate below. On rejection, relabel `triage`, add
   `**Escalated:**` after `Location` (values: report-format), leave
   `Disposition:` blank, and move on.
5. Before applying the selected solution, make a per-run backup directory under
   `$TMPDIR` and copy each existing file it will touch there at its
   repository-relative path. Record files that did not exist before the fix.
   This isolates the finding without disturbing earlier successful fixes, which
   a `git stash` or `git checkout` would also discard.
6. Apply only the selected solution.
7. Run the type check and tests scoped to the package in the finding's
   `location`; for a CI URL, run the failing check's local equivalent or the
   project's test suite. For a visual screenshot location, run checks for the
   UI source changed and repeat the visual flow with an inspected after image
   as in `references/visual.md`. Go full-repo when the fix spans packages.
8. In build mode, rerun the `assert:` lines of the plan tasks (from
   `plan_context`) whose `modifies`/`creates` cover the fixed file; standalone
   mode skips this.
9. On verification failure, copy the backed-up files to their original
   repository-relative paths, delete every file that did not exist before the
   fix, and leave the disposition blank.
10. Confirm the defect is gone before `Disposition: fix`: prefer a check that
    failed before the fix (existing test or step 8's `assert:` lines); one
    passing before and after proves nothing. With none, re-read the path
    against `Summary` and record "confirmed by inspection".

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

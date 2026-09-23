# Automated fix pass

## Dirty working tree (standalone invocation only)

If step 2 of `references/fix.md` found a dirty `repoRoot` during a standalone
run and the user accepted isolation, follow `references/worktree.md` with id
`review-fix-<review_dir>` and base set to the current branch. Use the printed
`path=` as the effective `repoRoot` for every step below. Use the `created=`
value to determine ownership. If you own the worktree, merge and clean it up
before human triage. This lets the user see applied fixes in their checkout.
If the merge reports a conflict, follow `references/worktree.md` with intent
"apply review findings from `<review_dir>`". Keep the worktree until the
conflict is resolved.

Process findings in category and file order. In a standalone run, process only
`Label: auto-fix` findings. Under a build (`mode=build`), process every finding
regardless of label.

For each finding:

1. Load the complete finding block.
2. Verify every location exists and still matches the recorded location.
3. Ask a fresh subagent to select the most reliable solution.
4. In build mode, run the escalation gate below against the selected solution.
   If the gate rejects it, send the finding to the human pass. Relabel it
   `triage` if it was `auto-fix`. Leave `Disposition: blank`, record the reason,
   and move on.
5. Record the current diff before applying the selected solution. Leave prior
   successful fixes in place.
6. Apply only the selected solution.
7. Run the type checker and tests for the package or file in the finding's
   `location`. For example, use `npx tsc --noEmit -p <package>` or
   `npm test -- <affected-test-path>`. Do not run the whole-repo command unless
   the fix touches files outside one package. Then use the full-repo
   `npx tsc --noEmit` or `npm test`. The build already verified this code once,
   so this scoped rerun checks the fix without rerunning the full suite for
   every finding.
8. Read the source task named by the finding's `location` field. If it has an
   optional `#### Verification` subsection with `assert:` lines, run every
   assertion and require all to pass. If the subsection is absent, skip this
   check.
9. On verification failure, restore only this finding's diff and leave the disposition
   blank.
10. On success, set `Disposition: fix`, and record the
    verification result.

If verification fails, continue with the next finding. Report each result with
its identifier and category.

A passing scoped run in step 7 proves that the fix introduced no regression. It
does **not** prove that the reported defect is gone. Before setting
`Disposition: fix`, confirm that the finding's defect no longer reproduces:

- Prefer a check that would have failed *before* the fix. Use an existing test
  that exercises the defect or the finding's task `assert:` lines (step 8). A
  test that passes before and after the fix does not verify this finding.
- If nothing exercises the defect, confirm resolution by re-reading the fixed
  code path against the finding's `Summary`. Record that inspection confirmed
  resolution instead of claiming a failing-then-passing test.

## When to defer to the user (under a build)

Step 4 checks this gate using the caller's `plan_context`, which contains the
plan goal, plan-level acceptance criteria, and `creates`/`modifies` scope.
Before applying a solution, check both conditions:

- **Spec conflict:** would the fix require the code to stop satisfying a
  plan-level acceptance criterion, or contradict something the plan explicitly
  specifies?
- **Scope creep:** would the fix change or break functionality outside the
  task's `creates`/`modifies` files, or introduce behavior the plan does not
  call for?

If either condition is true, send the finding to the human triage pass without
applying it. Add a bold `**Escalated:**` field right after `Location`. Use
`spec-conflict — <why>` or `scope-creep — <why>` as its value. The human pass
can then show the reason without deriving it again.

If neither condition is true, apply and verify the solution. This covers most
build findings, including findings labeled `triage` by the review.

# Automated fix pass

## Dirty-tree isolation (standalone invocation only)

If step 2 of `SKILL.md` found a dirty `repoRoot` on a standalone
invocation and the user accepted isolation, invoke the `varde-worktree` skill:
`create id=review-fix-<review_dir>` (base = current branch) and run every step
below with the printed `path=` as the effective `repoRoot`. Then follow
`varde-worktree`'s ownership rule: only when `create` returned `created=true`
do you `merge id=review-fix-<review_dir>` then `cleanup id=review-fix-<review_dir>`
once the merge lands cleanly — and merge before the human triage pass so the
user sees the applied fixes in their own checkout. If `created=false` (already
inside a caller's worktree, e.g. `mode=build`), do not merge or cleanup. If the
merge reports a conflict, follow the `varde-worktree` skill's
`references/RESOLVE.md` with intent "apply review findings from `<review_dir>`" —
do not clean up the worktree until that resolves.

Process findings in category and file order. In default mode, process only
`Label: auto-fix` findings. In `mode=build`, process every finding regardless
of label.

For each finding:

1. Load the complete finding block.
2. Verify every location exists and still matches the recorded location.
3. Ask a fresh subagent to select the highest-confidence solution.
4. In `mode=build`, run the escalation gate (below) against the selected
   solution. If it trips, do not apply — relabel the finding `triage` if it
   was `auto-fix`, leave `Disposition: blank`, record the reason, and move on
   to the next finding.
5. Record the current diff before applying the selected solution. Do not stash prior successful fixes.
6. Apply only the selected solution.
7. Run the type checker and tests scoped to the finding's own `location`
   package/file (e.g. `npx tsc --noEmit -p <package>` or `npm test --
   <affected-test-path>`), not the whole-repo command, unless the finding's
   fix touches files outside a single package — only then fall back to the
   full-repo `npx tsc --noEmit` / `npm test`. This finding was already
   verified once by the task subagent that authored it; a scoped rerun here
   confirms the fix without re-paying a second full-suite pass per finding.
8. Load the source task referenced by the finding's `location` field. If it
   has an optional `#### Verification` subsection with `assert:` lines, run
   every assertion and require all to pass. If the subsection is absent, skip
   this check.
9. On verification failure, restore only this finding's diff and leave the disposition
   blank.
10. On success, set `Disposition: fix`, and record the
    verification result.

Never mark a finding fixed before verification passes. Process later findings
after a failure. Report each result with its identifier and category.

A green scoped run in step 7 proves the fix introduced no regression; it does
**not** by itself prove the reported defect is gone. Before setting
`Disposition: fix`, confirm the finding's own defect no longer reproduces:

- Prefer a check that would have failed *before* the fix — an existing test
  that exercises the defect, or the finding's task `assert:` lines (step 8). A
  test that passes both before and after the fix is circular for this finding
  and proves nothing about it.
- If nothing exercises the defect, confirm resolution by re-reading the fixed
  code path against the finding's `Summary`, and record that the defect was
  confirmed resolved by inspection rather than by a failing-then-passing test —
  so the closing summary does not overstate the evidence.

## Escalation gate (`mode=build`)

Checked in step 4 of the automated fix pass, using the caller's
`plan_context` (plan goal, plan-level acceptance criteria, `creates`/`modifies`
scope). Before applying a solution, check both:

- **Spec conflict** — would the fix require the code to stop satisfying a
  plan-level acceptance criterion, or contradict something the plan explicitly
  specifies?
- **Scope creep** — would the fix change or break functionality outside the
  task's `creates`/`modifies` files, or introduce behavior the plan does not
  call for?

If either is true, the gate trips: skip application and hand the finding to
the human triage pass instead. Add a bold `**Escalated:**` field to the
finding, right after `Location`, with value `spec-conflict — <why>` or
`scope-creep — <why>` so the human pass can show it without re-deriving it.

If neither is true, apply and verify as normal — this covers most findings in
`mode=build`, including ones labeled `triage` by the review.

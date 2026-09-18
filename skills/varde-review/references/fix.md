# Fix mode

## Who invoked this

Standalone — a user asking to apply an existing review — is the default: the
automated pass covers only `Label: auto-fix` findings, and the human pass sees
every `Label: triage` finding.

`varde-change build` invokes this differently. It passes `mode=build` along with
`plan_context` (plan goal, plan-level acceptance criteria, `creates`/`modifies`
scope). Under it the automated pass covers **every** finding regardless of
label, and the human pass sees only findings the escalation gate rejected. If
`mode=build` arrives without `plan_context`, report a hard error and stop.

State which of the two is in effect before work starts.

## Workflow

1. **Load the instructions.** Read `references/fix-recipes.md`,
   `references/fix-interview.md`, and `references/fix-triage-pass.md`. The review
   folder is the source of truth. Read and edit its Markdown files directly.
2. **Confirm a clean working tree.** Run `git status --porcelain` in
   `repoRoot`. Under a build, the caller already runs this inside the build
   worktree, so the tree should already be clean — a dirty result there is a
   real error, so fail fast. In a standalone run with a non-empty result, leave
   the user's dirty state exactly as it is and offer to run the fix pass in a
   worktree per `references/worktree.md`; fail fast only if they decline.
   Full procedure: `references/fix-pass.md`.
3. **Select the review folder.** Resolve `review_dir` or the newest review
   folder, confirm `review.md` and generated nav-only `index.md` exist, and
   print the selected folder, category list, and finding counts before work
   starts.
4. **Run the automated fix pass.** Apply findings with per-finding diff isolation
   and verification, gated by the escalation check when invoked from a build. Full
   procedure: `references/fix-pass.md`.
5. **Run the human triage pass.** Walk whatever remains one at a time and ask
   for a disposition. Full procedure: `references/fix-triage-pass.md`.
6. **Simplify applied fixes.** If any finding was applied
   (automated or human `Disposition: fix`) and left uncommitted changes,
   invoke `references/simplify.md` scoped to those changes (working tree/staged
   diff) for a diff-scoped clarity pass — tighten naming and remove
   redundancy in what this pass just touched, verified by the project's
   tests before it reports back. Skip silently if no finding was applied.
7. **Create follow-up plans.** One plan per category that has action items.
   Full procedure: `references/fix-companion-plan.md`.
8. **Report the result.** Report fix and triage counts, update
   `triage_status`, and archive a completed standalone review. Full
   procedure: `references/fix-closing-summary.md`.
9. **Record lessons.** Invoke `varde-knowledge reflect`, scoped to this run. It
   records friction and durable lessons only — a handoff belongs at a
   session boundary, which this is not.

## Gotchas

- Verification-before-fix rule: see `references/fix-pass.md`.
- Diff isolation is per-finding. Preserve successful fixes and revert only
  the failed finding's own diff.
- Report mode creates the review folder and category files this pass consumes.
  `varde-change build` decomposes and executes a companion plan once this pass
  creates it — invoke it directly unless the companion plan's acceptance criteria
  are still vague, in which case route through `varde-change plan` first.
- If a review folder's markdown is malformed, report the category and finding
  identifier and stop until a human repairs it.

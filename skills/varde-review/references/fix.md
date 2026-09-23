# Fix mode

## Invocation mode

Standalone mode is the default. A user asks to apply an existing review.
The automated pass covers only `Label: auto-fix` findings. The human pass sees
every `Label: triage` finding.

`varde-change build` uses build mode. It passes `mode=build` with
`plan_context` containing the plan goal, plan-level acceptance criteria, and
`creates`/`modifies` scope. In build mode, the automated pass covers **every**
finding regardless of label. The human pass sees only findings rejected by the
escalation gate. If `mode=build` arrives without `plan_context`, report a hard
error and stop.

Before work starts, say whether this is standalone or build mode.

## Workflow

1. **Load the instructions.** Read `references/fix-recipes.md`,
   `references/fix-interview.md`, and `references/fix-triage-pass.md`. The review
   folder contains the authoritative files. Read and edit those Markdown files
   directly.
2. **Confirm a clean working tree.** Run `git status --porcelain` in
   `repoRoot`. In build mode, the caller already runs this inside the build
   worktree. The tree must be clean. A dirty result is an error, so stop at
   once. In standalone mode with a non-empty result, leave the user's dirty
   state unchanged. Offer to run the fix pass in a worktree using
   `references/worktree.md`. Stop only if the user declines.
   Full procedure: `references/fix-pass.md`.
3. **Select the review folder.** Resolve `review_dir`, or use the newest review
   folder. Confirm that `review.md` and generated nav-only `index.md` exist.
   Before work starts, print the selected folder, category list, and finding
   counts.
4. **Run the automated fix pass.** Apply findings with per-finding diff
   isolation and verification. In build mode, use the escalation check. Full
   procedure: `references/fix-pass.md`.
5. **Run the human triage pass.** Process remaining findings one at a time and
   ask for a disposition. Full procedure: `references/fix-triage-pass.md`.
6. **Simplify applied fixes.** If any finding was applied
   (automated or human `Disposition: fix`) and left uncommitted changes, invoke
   `references/simplify.md` on those changes in the working tree or staged diff.
   Tighten names and remove redundancy only from what this pass touched. The
   project's tests must verify the edits before this step reports back. Skip
   silently if no finding was applied.
7. **Create follow-up plans.** One plan per category that has action items.
   Full procedure: `references/fix-companion-plan.md`.
8. **Report the result.** Report fix and triage counts, update
   `triage_status`, and archive a completed standalone review. Full
   procedure: `references/fix-closing-summary.md`.
9. **Record lessons.** Invoke `varde-knowledge reflect` for this run. Record
   friction and durable lessons only. Record a handoff at a session boundary,
   not during this run.

## Gotchas

- Verify each finding before marking it fixed. See `references/fix-pass.md`.
- Diff isolation is per-finding. Preserve successful fixes and revert only
  the failed finding's own diff.
- Report mode creates the review folder and category files this pass consumes.
  After this pass creates a companion plan, `varde-change build` decomposes and
  executes it. Invoke `varde-change build` directly unless the companion plan's
  acceptance criteria are vague. In that case, use `varde-change plan` first.
- If a review folder's markdown is malformed, report the category and finding
  identifier and stop until a human repairs it.

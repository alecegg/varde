---
name: varde-review-fix
description: >
  TRIGGER: Apply findings from a /varde-review run. Run the isolated fix pass,
  verify each change, and triage deferred findings.
  SKIP: Skip only when the user wants a report-only review or new implementation
  unrelated to existing findings.
  Example phrases: "fix the review findings" or "apply this review".
---

## Entry point dispatch

| Invocation | Action |
|---|---|
| *(none)*, `mode=manual` | Automated pass covers only `Label: auto-fix` findings; human pass sees every `Label: triage` finding. |
| `mode=build` | Automated pass covers every finding regardless of label; human pass sees only findings the escalation gate rejected. Requires `plan_context` (plan goal, plan-level acceptance criteria, `creates`/`modifies` scope) — report a hard error and stop if `mode=build` is requested without it. |

Report the resolved mode before work starts.

## Workflow

1. **Load the references.** Load `references/RECIPES.md` — the curated call
   shapes for this skill's operations. Also load `references/INTERVIEW.md`
   for the harness-appropriate prompting format and `references/TRIAGE-PASS.md`
   for triage rules, dispositions, and recommendation guidance. The review
   folder is the source of truth — this skill reads and edits its markdown
   files directly, with no database-backed finding workflow.
2. **Confirm a clean working tree.** Run `git status --porcelain` in
   `repoRoot`. In `mode=build`, the caller already runs this skill inside the
   build worktree (see `/varde-build`'s `references/DISPATCH.md`), so this
   should already be clean — a dirty result there is a real error, fail fast. For a standalone invocation
   (no `mode`, or `mode=manual`) with a non-empty result, do not stash or
   commit on the user's behalf; instead offer to run the fix pass in a
   worktree isolated via the `varde-worktree` skill so unrelated dirty state in
   `repoRoot` is left untouched, and fail fast only if the user declines.
   Full procedure: `references/FIX-PASS.md`.
3. **Select the review folder.** Resolve `review_dir` or the newest review
   folder, confirm `review.md` and generated nav-only `index.md` exist, and
   print the selected folder, category list, and finding counts before work
   starts.
4. **Run the automated fix pass.** Apply findings with per-finding diff isolation
   and verification, gated by the `mode=build` escalation check. Full
   procedure: `references/FIX-PASS.md`.
5. **Run the human triage pass.** Walk whatever remains one at a time and ask
   for a disposition. Full procedure: `references/TRIAGE-PASS.md`.
6. **Run a simplify pass over the applied fixes.** If any finding was applied
   (automated or human `Disposition: fix`) and left uncommitted changes,
   invoke the `varde-simplify` skill scoped to those changes (working tree/staged
   diff) for a diff-scoped clarity pass — tighten naming and remove
   redundancy in what this pass just touched, verified by the project's
   tests before it reports back. Skip silently if no finding was applied.
7. **Create companion plans.** Emit one plan per category with action items,
   lazily on first use. Full procedure: `references/COMPANION-PLAN.md`.
8. **Report the closing summary.** Report fix/triage counts, update
   `triage_status`, and archive a completed standalone review. Full
   procedure: `references/CLOSING-SUMMARY.md`.
9. **Reflect and consolidate.** Invoke `varde-reflect source=varde-review-fix` — it
   captures friction scoped to this skill's own execution and harvests any durable
   knowledge the work produced (no handoff mid-session). If `varde-reflect` isn't
   installed, fall back to `varde-friction` with the same scope.

## Gotchas

- Verification-before-fix rule: see `references/FIX-PASS.md`.
- Diff isolation is per-finding. Preserve successful fixes and revert only
  the failed finding's own diff.
- `/varde-review` creates the review folder and category files this skill
  consumes; `/varde-build` decomposes and executes a companion plan after this
  skill creates it — invoke it directly unless the companion plan's acceptance
  criteria are still vague, in which case route through `/varde-plan` first.
- If a review folder's markdown is malformed, report the category and
  finding identifier and stop until it is repaired — do not guess at intent.

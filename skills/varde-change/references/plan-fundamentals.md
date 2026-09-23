# Plan Fundamentals

Use this breadth-first checklist during the growth loop
(`references/plan-grow-doc.md`). Run the closing step after resolving both
`## Open Questions` and `## Assumptions`.

## Breadth-first checklist

Before finalizing the draft, and whenever an answer sharpens the picture, map
every major area of the full scope. Do not rely on what came to mind first:

- Constraints (technical, product, time)
- Integration points
- Architecture / data-model decisions
- UX / workflow
- Operational concerns

Do not skip an area silently. If an area does not apply, note "n/a" and why,
inline while drafting or as a one-line note in `## Constraints`.

**External interface check:** If the destination touches code, config, or people
that already depend on it, flag it explicitly. Examples include an env var
consumed elsewhere, an exported public API/CLI flag, CI config, or a shared type. Do not
fold it into a generic note. Scan wider for consumers and record the wider
surface in the spec/AC so build sizes the corresponding task(s) with more
scrutiny at decomposition time
(`references/plan-acceptance-criteria.md`'s scope indicators); a narrow internal-only change
doesn't need the same diligence.
When `varde-code` is available (`references/varde-code.md`), run
`dependents`/`blast_radius` on the touched file or symbol to find actual
consumers instead of guessing — a wider-than-expected result is itself grounds to
flag.

Record the query and a short evidence summary in every affected task's
`#### Impact evidence` section. Confirm the important consumers and relevant
tests with focused source reads. Convert each confirmed consumer into an exact
`impact:<repo-relative-path>` entry in `verification_resources`. Those
identifiers are opaque after the `impact:` prefix and must not be normalized by
later scheduling steps.

If `varde-code` is unavailable, use manual dependency analysis. Name the
inspected consumers and relevant tests in the same evidence section. Manual
evidence remains valid, but a missing or uncertain consumer blocks parallel
eligibility until the task is narrowed or the relationship is confirmed.

## Self-review checklist

An empty `## Open Questions` alone isn't grounds to stop. Hunt for gaps first:

- **Placeholders:** Re-read the plan body for TBD, "figure out later", or any
  Design subsection still too vague to implement.
- **Contradictions:** Do two confirmed decisions conflict, or does a later
  decision silently invalidate an earlier one?
- **Scope gaps:** Does Non-goals actually cover everything implied by the
  Solution, or is there a boundary nobody asked about?
- **Ambiguity:** Any confirmed decision still admitting two valid
  implementations — pick the interpretation that best matches the spec, then add
  it to `## Open Questions` as a normal item rather than assuming.

If this scan finds anything, add it to `## Open Questions` and continue the loop
(`references/plan-grow-doc.md`). Do not add it only as an afterthought to the
final completeness check below.

## Step 4: Metadata and closing

Once `## Open Questions` and `## Assumptions` are both resolved:

1. Propose a slug from the plan's title or problem statement (lowercase,
   hyphenated); ask the user to confirm or change it — follow the recommendation
   requirement from `references/plan-interview.md`. Wait for their answer.
2. Ask separately whether the plan includes a frontend/UI surface; wait. If yes,
   invoke `varde-prototype` and wait for it to complete. Use its output to shape
   the acceptance criteria and later build decomposition.
3. If the temporary slug differs, rename the draft plan directory to the
   confirmed slug (the plan id is its directory name):
   `git mv <working>/plans/<old-plan-id> <working>/plans/<new-plan-id>`
   (plain `mv` when `<working>` is redirected outside the repository or
   git-ignored).

Then, in order:

1. Replace any `## Design` subsection still containing only
   `(filled during planning)` with `(none)`.
2. Preserve the storage mode selected in `references/plan.md` step 2. Keep
   ignored plans local.
   Stage and commit only this plan's directory when the plan is tracked.
3. Ask the **final completeness check** by pointing at the plan file instead of
   restating its contents: "Anything left to resolve before we finalize the
   plan?" This check looks for missed items, not scope decisions. Wait for
   explicit confirmation before continuing without more questions.

After confirmation, continue without more questions. Use a subagent to evaluate plan
boundaries: identify independently shippable candidates, each with slug, title,
goal, constraints, non-goals, dependency candidates.

- **Single candidate:** apply the result to the draft plan directly —
  `shape: "single"`, one plan total. Continue to finalize the plan (AC review
  and storage-aware persistence, `references/plan-authoring.md`).
- **Multiple candidates:** read `references/plan-splitting.md` and follow it to
  confirm the split with the user and spawn one plan per candidate.

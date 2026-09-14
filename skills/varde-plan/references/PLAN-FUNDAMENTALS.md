# Plan Fundamentals

Breadth-first checklist for the growth loop (`references/GROW-DOC.md`) plus
the closing step, run once `## Open Questions` and `## Assumptions` are both
resolved.

## Breadth-first checklist

Before finalizing the draft (or re-scanning after an answer sharpens the
picture), map every major area of the full scope — don't rely on what came to
mind first:

- Constraints (technical, product, time)
- Integration points
- Architecture / data-model decisions
- UX / workflow
- Operational concerns

Don't skip an area silently. If it doesn't apply, note "n/a" and why — inline
while drafting or as a one-line note in `## Constraints`.

**External contract surface signal.** If the destination touches something other
code, config, or people already depend on — an env var consumed elsewhere, an
exported public API/CLI flag, CI config, a shared type — flag it explicitly
instead of folding it into a generic note. This signals to scan wider for
consumers and to record the wider surface in the spec/AC so build sizes the
corresponding task(s) with more scrutiny at decomposition time
(`ACCEPTANCE-CRITERIA.md`'s scope signals); a narrow internal-only change
doesn't need the same diligence.
When `varde-code` is available (`references/VARDE-CODE-CLI.md`), run
`dependents`/`blast_radius` on the touched file or symbol to find actual
consumers instead of guessing — a wider-than-expected result is itself grounds to
flag.

## Self-review checklist

An empty `## Open Questions` alone isn't grounds to stop. Hunt for gaps first:

- **Placeholders.** Re-read the plan body for TBD, "figure out later", or any
  Design subsection still too vague to implement.
- **Contradictions.** Do two confirmed decisions conflict, or does a later
  decision silently invalidate an earlier one?
- **Scope gaps.** Does Non-goals actually cover everything implied by the
  Solution, or is there a boundary nobody asked about?
- **Ambiguity.** Any confirmed decision still admitting two valid
  implementations — pick the interpretation that best matches the spec, then add
  it to `## Open Questions` as a normal item rather than assuming.

If this scan surfaces anything, add it to `## Open Questions` and keep iterating
(`GROW-DOC.md`) — don't fold it into the completeness gate below as an
afterthought.

## Step 4: Metadata and closing

Once `## Open Questions` and `## Assumptions` are both resolved:

1. Propose a slug from the plan's title or problem statement (lowercase,
   hyphenated); ask the user to confirm or change it — follow the recommendation
   requirement from `INTERVIEW.md`. Wait for their answer.
2. Ask separately whether the plan includes a frontend/UI surface; wait. If yes,
   invoke `/varde-prototype` and wait for it to complete — its output shapes the
   acceptance criteria (and, later, build's decomposition).
3. If the temporary slug differs, rename the draft plan directory to the
   confirmed slug (the plan id is its directory name):
   `git mv memory-bank/working/plans/<old-plan-id> memory-bank/working/plans/<new-plan-id>`

Then, in order:

1. Replace any `## Design` subsection still containing only
   `(filled during planning)` with `(none)`.
2. Commit the proposal:
   ```bash
   git add memory-bank/working/plans/<plan-id>/plan.md && git commit -m "plan(<plan-id>): proposal"
   ```
3. Ask the **completeness gate**: point at the plan file rather than re-stating
   its contents, and ask "Anything left to resolve before we finalize the plan?"
   This is a final missed-nothing check, not a scope check — wait for explicit
   confirmation before entering post-spec autopilot.

After confirmation, enter post-spec autopilot. Use a subagent to evaluate plan
boundaries: identify independently shippable candidates, each with slug, title,
goal, constraints, non-goals, dependency candidates.

- **Single candidate:** apply the result to the draft plan directly —
  `shape: "single"`, one plan total. Continue to finalize the plan (AC review
  and commit, `PLAN-AUTHORING.md`).
- **Multiple candidates:** read `references/PLAN-SPLITTING.md` and follow it to
  confirm the split with the user and spawn one plan per candidate.

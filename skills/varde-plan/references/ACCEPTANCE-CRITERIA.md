# Acceptance criteria & scope signals

Covers the plan's `## Acceptance criteria` — the plan-level contract of "done"
for the whole change — and the scope signals that must be caught at plan time
because they change the spec, the AC, or the split.

Acceptance criteria are **plan-level**, not per-task. They describe what must be
observably true once the change ships, independent of how the work is later
sliced into tasks. Decomposition is not done here — it's `/varde-build`'s job
(`varde-build/references/DECOMPOSITION.md`).

## Acceptance-criteria review

Grow the criteria inline in the living-doc loop (`GROW-DOC.md`), then run this
review over the full set before the completeness gate.

**Assert vs. retrieve:**
- `assert:` — structural facts checkable mechanically (a command, a grep, a test
  run). Pass/fail, no LLM judgment.
- `retrieve:` — when the LLM must judge fetched output; point at the specific
  file(s) or grep to read, not a full-file read.

**Prefer `assert:` — a criterion the agent grades against its own output is the
weakest kind of "done."** An `assert:` criterion is checked by something outside
the agent (a command that exits non-zero, a grep that finds or doesn't, a test
that fails); a `retrieve:` criterion is the agent judging text it just produced,
which it is biased to pass. Before accepting any `retrieve:`, try to restate it
as an `assert:` — name the command, exit code, file existence, or non-empty
output that would make the same claim mechanically. Keep `retrieve:` only when
the outcome genuinely needs semantic judgment no command can stand in for (e.g.
"the error message explains the cause"), and say in the criterion what the judge
must look for. A criterion no command can check and no reader can judge from a
named file is not yet an acceptance criterion.

**GWT compliance.** Each criterion must contain `Given`, `When`, and `Then`
lines in that order. For any that fails, rewrite into Given/When/Then form and
re-score for testability before writing to the plan.

**Score testability.** Spawn a scoring subagent for the full criteria set. It
outputs a JSON array of `{ criterion, testable: boolean, reason }` — one entry
per criterion. Validate: array with one entry per criterion, `criterion` matches
verbatim, `testable` is boolean, `reason` is non-empty. If malformed, surface
raw output and stop. For any `testable: false` entry, automatically rewrite the
criterion using the scoring reason and confirmed scope, and re-score after every
rewrite. Repeat until all pass or a faithful rewrite is impossible (stop with a
blocker). Never ask the user to approve an AC rewrite.

Criteria are the observable outcomes of the *change*, not of an arbitrary slice.
Write each at the level of a public behavior or workflow rule the user can point
at — not the internal step count build will later choose.

## Scope signals — catch these at plan time

Some patterns don't just affect how work is sliced; they change scope, AC, or
whether the plan should split. Catch them during the breadth-first /
completeness check (`PLAN-FUNDAMENTALS.md`) so the spec and AC are right before
build ever decomposes. Build re-derives the *slicing* from the spec
(`DECOMPOSITION.md` owns the expand→migrate→contract / upfront-foundation
mechanics); the plan's job is only to make sure the scope-affecting fact is
recorded, not left for build to discover mid-run.

- **Wide refactor.** If the goal names a shared symbol, type, or interface, find
  its blast radius before assuming a small footprint — grep usages/dependents,
  or run `symbol_blast_radius` when `varde-code` is available
  (`references/VARDE-CODE-CLI.md`). A result fanning across many independent
  packages is itself grounds to flag in `## Design`/`## Constraints` and to weigh
  a plan split — it can't land as one green slice.
- **Native scan rule port → data availability.** If the change ports a native
  scan rule to TOML/SQL, native rules can read `entity.data.<field>` values the
  persisted schema never populates. Read each rule's implementation, list every
  `entity.data.<field>` it accesses, and check each against the persisted schema
  (read the db/schema module directly — don't assume it matches a sibling rule).
  Any unpopulated field is a **data-foundation scope item**: record it in the
  spec/AC as a prerequisite (an indexer must write it first), so build makes it
  an upfront task rather than discovering the gap mid-port.
- **Deletion of a shared artifact.** If the change deletes a generated or
  intermediate artifact another part of the system reads, note the downstream
  textual consumers (a hardcoded fixture path, a `readFileSync` call, a
  string-literal path a structural query can't see) in the spec so the ordering
  constraint is explicit before decomposition.

## Record the finalized criteria

Apply a targeted edit to `plan.md`'s `## Acceptance criteria` section with the
finalized, reviewed criteria (one Given/When/Then block per line, each tagged
`assert:` or `retrieve:`). This is the only acceptance-criteria surface — do not
author per-task criteria; build owns the task files and their `#### Verification`
blocks.

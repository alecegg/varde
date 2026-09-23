# Acceptance criteria & scope indicators

Covers the plan's `## Acceptance criteria`, the plan-level definition of done
for the whole change, and scope indicators. Catch scope indicators during
planning because they can change the spec, AC, or split.

Acceptance criteria are **plan-level**, not per-task. They describe what must be
observably true after the change ships, regardless of how the work is later
sliced into tasks. `varde-change build` handles decomposition
(`references/build-decomposition.md`).

## Acceptance-criteria review

Grow the criteria in the plan-document loop
(`references/plan-grow-doc.md`). Run this review over the full set before the
final completeness check.

**Assert vs. retrieve:**
- `assert:` — structural facts checked mechanically by a command, grep, or test
  run. The result is pass or fail, with no LLM judgment.
- `retrieve:` — use when an LLM must judge fetched output. Point to the specific
  file(s) or grep to read, not a full-file read.

**Prefer `assert:`.** A criterion the agent grades against its own output is the
weakest kind of "done." An `assert:` criterion is checked outside the agent by a
command exit code, grep result, or test. A `retrieve:` criterion asks the agent
to judge text it just produced, which biases the result. Before accepting
`retrieve:`, try to restate it as `assert:` by naming a command, exit code, file
existence, or non-empty output. Keep `retrieve:` only when the outcome needs
semantic judgment that no command can provide, such as whether an error message
explains the cause. State what the judge must look for. A criterion that no
command can check and no reader can judge from a named file is not an acceptance
criterion.

**GWT compliance:** Each criterion must contain `Given`, `When`, and `Then`
lines in that order. Rewrite any criterion that fails, then re-score it for
testability before writing it to the plan.

**Score testability.** Spawn a scoring subagent for the full criteria set. It
outputs a JSON array of `{ criterion, testable: boolean, reason }`, with one
entry per criterion. Validate that the output is an array with one entry per
criterion, that `criterion` matches verbatim, that `testable` is boolean, and
that `reason` is non-empty. If the output is malformed, show the raw output and
stop. For each `testable: false` entry, automatically rewrite the criterion
using the scoring reason and confirmed scope. Re-score after every rewrite.
Repeat until all pass or a faithful rewrite is impossible; stop with a blocker
in that case. Rewriting is automatic; the user sees the finalized set.

Criteria describe observable outcomes of the *change*, not an arbitrary slice.
Write each at the level of a public behavior or workflow rule the user can point
to, not the internal step count that build later chooses.

## Scope signals — catch these at plan time

Some patterns affect more than task slicing. They change scope, AC, or whether
the plan should split. Catch them during the breadth-first and completeness
check (`references/plan-fundamentals.md`) so the spec and AC are correct before
build decomposes anything. Build re-derives the *slicing* from the spec
(`references/build-decomposition.md` owns the expand→migrate→contract / upfront-foundation
steps); the plan's job is only to make sure the scope-affecting fact is
recorded, not left for build to discover mid-run.

- **Wide refactor:** If the goal names a shared symbol, type, or interface, find
  its blast radius before assuming a small footprint. Grep usages/dependents,
  or run `symbol_blast_radius` when `varde-code` is available
  (`references/varde-code.md`). A result fanning across many independent
  packages is grounds to flag it in `## Design`/`## Constraints` and weigh a
  plan split. It cannot land as one green slice.
- **Native scan rule port → data availability:** If the change ports a native
  scan rule to TOML/SQL, native rules can read `entity.data.<field>` values the
  persisted schema never populates. Read each rule's implementation, list every
  `entity.data.<field>` it accesses, and check each against the persisted schema
  (read the db/schema module directly — don't assume it matches a sibling rule).
  Any unpopulated field is a **data-foundation scope item**: record it in the
  spec/AC as a prerequisite (an indexer must write it first), so build makes it
  an upfront task rather than discovering the gap mid-port.
- **Deletion of a shared file:** If the change deletes a generated or
  intermediate file another part of the system reads, note the downstream
  textual consumers (a hardcoded fixture path, a `readFileSync` call, a
  string-literal path a structural query can't see) in the spec so the ordering
  constraint is explicit before decomposition.

## Record the finalized criteria

Apply a targeted edit to `plan.md`'s `## Acceptance criteria` section with the
finalized, reviewed criteria (one Given/When/Then block per line, each tagged
`assert:` or `retrieve:`). This is the only acceptance-criteria surface; build
owns the task files and their `#### Verification` blocks.

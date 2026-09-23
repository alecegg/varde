# Plan splitting into multiple candidates

Use this when splitting a completed plan at `references/plan-fundamentals.md`
Step 4, after the full spec is known. This is the only split point, so judge
boundaries from real information instead of a pre-spec guess.

## Steps

- **Data-backed boundaries:** When `varde-code` is available
  (`references/varde-code.md`), run `clusters` on the affected files. Densely
  interconnected files suggest one candidate rather than several. Confirm or
  override the result; it is a starting point, not a verdict.
- **Confirm with the user first.** Before creating child plans, list each
  candidate title and dependency order in a brief message. Ask: "Does this
  decomposition look right, or should any of these be combined or split
  differently?" Wait for acknowledgment.
- **Create nested child plans.** Once confirmed, create one new **nested** child
  plan directory per candidate under the current plan's directory:
  `<working>/plans/<plan-id>/<child-slug>/plan.md`. This nesting gives
  the child its compound Concept ID (`<plan-id>/<child-slug>`) and is how group
  membership is derived — do not add `children:` or `parent:` frontmatter fields
  (`children:`/`parent:` are for tasks linking to their plan, not plan grouping).
  Each candidate proceeds through AC review and plan finalization independently
  in its own nested directory; task decomposition happens later, per child plan,
  in `varde-change build`.
- **Repurpose the current plan as group parent.** Keep it rather than discarding:
  targeted edit to its `plan.md` frontmatter to set `shape: group`. A group plan
  has no children stored as a list — they are discovered by directory nesting —
  so it skips AC review and plan finalization entirely; it only ever needs the
  goal/non-goals/constraints recorded.

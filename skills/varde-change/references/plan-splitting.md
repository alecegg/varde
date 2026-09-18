# Plan splitting into multiple candidates

Used when splitting a completed plan (`references/plan-fundamentals.md` Step 4, run once the full
spec is known) — the only point a plan gets split, so boundaries are judged from
real information instead of a pre-spec guess.

## Steps

- **Data-backed boundaries:** When `varde-code` is available
  (`references/varde-code.md`), run `clusters` on the affected files —
  densely interconnected files suggest one candidate rather than several.
  Confirm or override it; it is a starting point, not a verdict.
- **Confirm with the user first.** Before creating child plans, list each
  candidate title and the dependency order in a brief message, then ask: "Does
  this decomposition look right, or should any of these be combined or split
  differently?" Wait for acknowledgment.
- **Create nested child plans.** Once confirmed, create one new **nested** child
  plan directory per candidate under the current plan's directory:
  `memory-bank/working/plans/<plan-id>/<child-slug>/plan.md`. This nesting gives
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

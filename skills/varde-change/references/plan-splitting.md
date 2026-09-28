# Plan splitting into multiple candidates

Use this when the self-review or independent review in
`references/plan-fundamentals.md` finds several shippable changes. This is the
only split point, so boundaries come from the full spec rather than a pre-spec
guess.

1. **Data-backed boundaries.** With `varde-code` available, run `clusters` on
   the affected files; densely interconnected files suggest one candidate. It
   is a starting point, not a verdict.
2. **Confirm with the user.** List each candidate title and the dependency
   order, ask whether any should be combined or split differently, and wait.
3. **Create nested child plans**, one per candidate:
   `<working>/plans/<plan-id>/<child-slug>/plan.md`. Nesting gives the child its
   compound id (`<plan-id>/<child-slug>`) and its group membership — no
   `children:`/`parent:` fields. Each child goes through AC review and
   finalization on its own; `varde-change build` decomposes each later.
4. **Keep the current plan as the group parent**: set `shape: group` in its
   frontmatter. It keeps goal, non-goals, and constraints plus an aggregate contract outside
   Progress: source scope, each child ID/dependencies/contract, assumptions,
   and aggregate acceptance/verification. Child contracts remain individually
   finalized. Validate and commit the group parent together with its children
   (tracked storage); orchestration obtains its own aggregate review gates.

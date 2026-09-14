## Storing the plan doc

When `varde-docs` is present, the living plan doc is a concept in a bundle
rooted at the plan directory, so every growth-loop write is OCC-safe. This
matters most in **in-doc collaboration mode** (below), where the user and an
agent may write the same doc: the version hash prevents a clobber.

```bash
BUNDLE=<plan-dir>          # the directory that holds plan.md
SLUG=plan                  # plan.md → slug "plan"

# Step 3 (create + seed): create the doc from the seeded draft.
varde-docs concept create --bundle "$BUNDLE" "$SLUG" --file "${TMPDIR:-/tmp}/plan-seed.md"

# Step 4 (grow, each turn): show → read its "version" → edit → update with that
# hash. On exit 3, re-show and fold the user's concurrent edit in before retrying.
varde-docs concept show --bundle "$BUNDLE" "$SLUG" --json   # note the "version" value
varde-docs concept update --bundle "$BUNDLE" "$SLUG" --expected-version <version> --file "${TMPDIR:-/tmp}/plan-next.md"
```

Fall back to plain Read/Write/Edit on any failure. Task files
(`tasks/<id>.md`, step 5) are ordinary files authored the same way as today —
they don't need the CLI, though `create` works for them too.

## In-doc collaboration mode (docwatch)

`docwatch` (a sibling CLI in the same repo, optional, macOS/launchd) lets the
user steer the plan by editing the doc from anywhere (e.g. iOS over
Tailscale): a line `@c: <steer>` in the doc dispatches an agent that runs one
growth turn and writes the answer back in place. This is the same "user edits
`plan.md` between turns" channel the skill already uses (step 4), made
agent-responsive without a live session.

Set it up early, in step 3, when the user wants this mode:

```bash
docwatch add <plan-dir>        # register the folder; starts a watcher
docwatch list --json           # confirm it's watching
```

Seed the doc's top with a trigger contract so a dispatched agent adopts this
skill's stance rather than docwatch's generic "answer inline" prompt:

```markdown
<!-- docwatch: on an `@c:`/`@cx:` trigger, load /varde-plan and treat the
     trigger text as one growth-loop turn on this doc. Grow the doc, route
     unknowns to ## Open Questions / ## Assumptions, write the result in
     place. Do not create or edit any other file. -->
```

Two boundaries make this safe and coherent:

- **Path.** docwatch watches a persistent folder, so in this mode the doc
  lives at its **stable plan path** for the whole growth phase — not inside a
  throwaway worktree (see step 2). The user must be able to reach the same
  path the agent writes.
- **Phase.** docwatch reverts any write outside the triggering doc, so it fits
  **only the growth phase** (single living `plan.md`). Task authoring (step 5)
  writes `tasks/*.md` — multiple files — and must run in a normal session,
  outside docwatch. Stop in-doc mode before authoring; `docwatch remove
  <plan-dir>` once the plan is done if the folder shouldn't stay watched.

If either tool is absent, grow the plan through live chat in the current
checkout. Use worktree isolation only when step 2 selects it.

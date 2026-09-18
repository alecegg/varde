# Optional `varde-docs` and `docwatch` CLIs

`varde-docs` is an optional Rust tool on PATH. It manages markdown with
frontmatter and safe concurrent writes. Check once per session:

```bash
command -v varde-docs >/dev/null 2>&1
```

Absent, ignore this file and use plain Read/Write/Edit/Grep for the same
operations.

## Output and exit codes

With `--json`, a successful command prints its result JSON straight to stdout
(e.g. `show --json` prints `{"slug","version","frontmatter","body","created","updated"}`)
— there is no `{"ok":...}` wrapper. A failure prints `{"error": "..."}` and
sets a distinct **exit code**, so branch on `$?`, not on message text:

- `0` — success (stdout is the result)
- `1` — infrastructure/parse failure
- `2` — not found
- `3` — OCC version conflict (`--expected-version` is stale)
- `4` — invalid input (bad slug, validation failure)
- `5` — already exists (`create` only)

## The OCC read-then-write contract

Writes (`update`, `set-field`) require `--expected-version`, the version hash
last read via `show`, and reject a stale write instead of silently
overwriting. Always:

1. `show --bundle <dir> <slug> --json` → read the current `version`.
2. Compute the new content, then `update`/`set-field` with
   `--expected-version <that hash>`.
3. On **exit 3** (conflict) someone else wrote in between — re-`show`,
   reconcile against the new content, and retry. Never pass a guessed or
   reused hash.

This is the main reason to prefer the CLI when it's available: it makes
concurrent writers (a live agent and a user editing the same doc) safe.

## Store the plan document

Store the plan in a bundle rooted at the plan directory — the directory holding
`plan.md`, whose slug is `plan`.

```bash
BUNDLE=<plan-dir>
SLUG=plan

# Create and seed the doc from the seeded draft.
varde-docs concept create --bundle "$BUNDLE" "$SLUG" --file "${TMPDIR:-/tmp}/plan-seed.md"

# Each growth turn: show, read its "version", edit, update with that hash.
varde-docs concept show   --bundle "$BUNDLE" "$SLUG" --json
varde-docs concept update --bundle "$BUNDLE" "$SLUG" --expected-version <version> --file "${TMPDIR:-/tmp}/plan-next.md"
```

Task files are ordinary files authored the same way as today. They do not need
the CLI, though `create` works for them too.

## In-doc collaboration mode (docwatch)

`docwatch` is a sibling optional CLI (macOS/launchd) that lets the user steer the
plan by editing the doc from anywhere. A line `@c: <steer>` in the doc dispatches
an agent that runs one growth turn and writes the answer back in place — the same
"user edits `plan.md` between turns" channel the growth loop already uses, made
agent-responsive without a live session.

Set it up early, when creating the doc, if the user wants this mode:

```bash
docwatch add <plan-dir>        # register the folder; starts a watcher
docwatch list --json           # confirm it's watching
```

Seed the doc's top with a trigger contract so a dispatched agent adopts this
skill's stance rather than docwatch's generic "answer inline" prompt:

```markdown
<!-- docwatch: on an `@c:`/`@cx:` trigger, load varde-change plan and treat the
     trigger text as one growth-loop turn on this doc. Grow the doc, route
     unknowns to ## Open Questions / ## Assumptions, write the result in
     place. Do not create or edit any other file. -->
```

Two boundaries keep this safe:

- **Path:** docwatch watches a persistent folder, so the doc lives at its
  **stable plan path** for the whole growth phase — never inside a throwaway
  worktree. The user must be able to reach the same path the agent writes.
- **Phase:** docwatch reverts any write outside the triggering doc, so it fits
  **only the growth phase**, with its single living `plan.md`. Task authoring
  writes several `tasks/*.md` files and must run in a normal session outside
  docwatch. Stop in-doc mode before authoring, and `docwatch remove <plan-dir>`
  once the plan is done if the folder should not stay watched.

If either tool is absent, grow the plan through live chat in the current
checkout, isolating only when the plan mode's location step selects it.

## Fallback rule

If the sandbox denies access to a path outside the workspace — the Personal
vault under `~/.varde-docs/`, or a lock beside it — retry that call once with
escalated filesystem access, keeping the command unchanged. If approval is
unavailable, denied, or the retry fails, use Read/Write/Edit/Grep for that
operation and name the degraded capability in your next message.

On any other failure, fall back to Read/Write/Edit/Grep for that one operation
— don't block on it or try to build/install it yourself. An absent binary is
not an error and needs no report.

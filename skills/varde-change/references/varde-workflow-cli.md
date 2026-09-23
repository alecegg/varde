# Optional `varde-workflow` and `docwatch` CLIs

`varde-workflow` is an optional Rust tool on PATH. It manages markdown with
frontmatter and safe concurrent writes. Check once per session:

```bash
command -v varde-workflow >/dev/null 2>&1
```

If unavailable, plain Read and Grep may continue visibly degraded.
Stop before CLI-owned mutations. Use CLI state and concept commands.

## Decision rule

- **Known content:** Read one known artifact directly when no mutation follows.
- **Discovery:** Search unknown candidates. Use list or maps for inventories.
- **Mutation:** Use state commands when applicable. Use OCC concept writes.
- **Output scope:** Use text for reading. Request JSON for required fields.
- **Candidate reads:** Search first. Show only selected concepts.

## Output and exit codes

With `--json`, every command prints one versioned envelope.
Success uses `{"envelope_version":1,"ok":true,"data":...}`.
Failure uses `{"envelope_version":1,"ok":false,"error":...}`.
Branch on exit status before reading either payload:

- `0` — success (stdout is the result)
- `1` — infrastructure/parse failure
- `2` — not found
- `3` — OCC version conflict (`--expected-version` is stale)
- `4` — invalid input (bad slug, validation failure)
- `5` — already exists (`create` only)

Read command payloads from `data`. Before rewriting legacy artifacts,
run `varde-workflow migrate <path> --apply` explicitly.


## The workflow state machine

These states are fixed by the workflow schema, not by any skill. Writing a
status the schema does not know (`draft`, or a task in the plan's `backlog`)
makes every later CLI call fail with `unknown status`.

| Artifact | States | Initial | Legal moves |
|---|---|---|---|
| `plan` | `backlog`, `active`, `blocked`, `completed` | `backlog` | `backlog`→`active`/`blocked`; `active`→`blocked`/`completed`; `blocked`→`active`; `completed` is terminal |
| `task` | `todo`, `in_progress`, `blocked`, `done` | `todo` | `todo`→`in_progress`/`blocked`; `in_progress`→`blocked`/`done`; `blocked`→`in_progress`; `done` is terminal |

There is no `todo`→`done` shortcut. A task that never entered `in_progress`
cannot be completed, and a plan left in `backlog` cannot reach `completed` — so
`conclude` fails at the end of an otherwise clean run.

**Read state before changing it.** Use `readiness` to see the artifact's legal
next states and blockers:

```bash
varde-workflow readiness <plan.md> --json
# data.actions  -> legal next states, e.g. ["active","blocked"]
# data.blockers -> unmet dependencies; non-empty means hold this plan back
# data.ready    -> false when a blocker applies
```

Use `graph` to see dependency order across sibling artifacts:

```bash
varde-workflow graph <any-sibling>/plan.md --json
# data.nodes  -> {id, status, path} per sibling
# data.edges  -> {from, to, relationship: "depends_on"}
# data.schema -> the state table above, live from the schema
```

Invoke `graph` on **a sibling, not the parent**. It resolves the set around the
artifact it is handed; given a group `plan.md` it returns that one node and no
edges, which reads like a group with no children.

**Change state through `transition`, never by editing frontmatter.**

```bash
varde-workflow transition <artifact.md> <state> --json
```

A rejected transition returns `error.code: workflow_blocked` with
`details.current_state`, `details.requested_state`, and `details.allowed_states`.
It leaves every source byte unchanged. An accepted transition writes through the
staged journal, so `recover --root <project-root>` can finish an interrupted
write. A hand-edited frontmatter status skips validation and gives `recover`
nothing to repair.

**Validate without mutating** when you want diagnostics but no state change:
`varde-workflow validate <artifact.md> --json`. `inspect` returns the resolved
envelope and content revision; on a pre-kernel document it sets `legacy` and
`migration_required`, and `migrate <path> --apply` is the only thing that
rewrites it.

Use `conclude` after every criterion and observed spec pass. Use
`conclusion-status` to inspect qualitative follow-up, `conclusion-retry` to reset
failed follow-up, and `conclusion-action` to record a completed follow-up.

## The OCC read-then-write contract

Writes (`update`, `set-field`) require `--expected-version`, the version hash
last read via `show`, and reject a stale write instead of silently
overwriting. Always:

1. `show --bundle <dir> <slug> --json` → read `data.version`.
2. Compute the new content, then `update`/`set-field` with
   `--expected-version <that hash>`.
3. On **exit 3** (conflict), someone else wrote in between. Re-read with
   `show`, reconcile against the new content, and retry. Never pass a guessed
   or reused hash.

Prefer this CLI because it protects concurrent edits by a live agent and a user.
It also provides ranked `search` and consistent whole-document reads.

## Store the plan document

Store the plan in a bundle rooted at the plan directory — the directory holding
`plan.md`, whose slug is `plan`.

```bash
BUNDLE=<plan-dir>
SLUG=plan

# Create and seed the doc from the seeded draft.
varde-workflow concept create --bundle "$BUNDLE" "$SLUG" --file "${TMPDIR:-/tmp}/plan-seed.md"

# Each growth turn: show, read its "version", edit, update with that hash.
varde-workflow concept show   --bundle "$BUNDLE" "$SLUG" --json
varde-workflow concept update --bundle "$BUNDLE" "$SLUG" --expected-version <version> --file "${TMPDIR:-/tmp}/plan-next.md"
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

If `docwatch` is absent, grow plans through live chat.
If `varde-workflow` is absent, stop before artifact writes.

## Fallback rule

If the sandbox denies access to a path outside the workspace, such as the
Personal vault under `~/.varde-workflow/` or a lock beside it, retry that call
once with escalated filesystem access, keeping the command unchanged. If
approval is unavailable, denied, or the retry fails, stop every mutation.
Continue read-only operations with Read or Grep, and state the degraded
capability.

On any other failure, stop mutations without changing bytes.
For other read-only failures, report the lost capability and continue with
degraded reads.
Never build or install the binary during another workflow.

# Optional varde-docs CLI

`varde-docs` is a standalone, pre-alpha Rust CLI installed on PATH as
`varde-docs` (CLI-only — no MCP server surface). It's a generic
markdown-with-frontmatter store: concept CRUD, optimistic-concurrency
(compare-and-swap) writes, Personal/Project vault layering, ranked full-text
search, and an opt-in lint. It's optional: use it when available for
conflict-safe writes and ranked search, and fall back to plain
Read/Write/Edit/Grep/Glob when it isn't. Check once per session whether it's
installed:

```bash
command -v varde-docs >/dev/null 2>&1
```

If `varde-docs` is not installed, ignore this file and use plain
Read/Write/Edit/Grep/Glob for the same operations. Do not build or install it,
and don't treat its absence as an error.

## Vocabulary map

The CLI's OKF vocabulary maps onto the artifacts these skills already manage:

- **Concept** = one markdown file with YAML frontmatter (a knowledge note, a
  plan doc, any `<slug>.md`).
- **Slug** = the file's bundle-root-relative path, `/`-separated, `.md`
  stripped, kebab-case segments. A nested file
  `memory-bank/knowledge/pattern/code-review.md` under bundle root
  `memory-bank/knowledge/` has slug `pattern/code-review`.
- **Bundle** = a directory tree of concept `.md` files, passed as
  `--bundle <dir>`. Walks recurse at any depth.
- **Vault** = the Personal (`~/.varde-docs/`) vs Project (a repo bundle)
  layering that `list`/`search`/`lint` merge by default (Project wins on a
  same-slug collision); `--vault personal|project` narrows to one side.

## Command surface

```bash
varde-docs concept create   --bundle <dir> <slug>            # body from stdin
varde-docs concept create   --bundle <dir> <slug> --file <path>
varde-docs concept show     --bundle <dir> <slug> [--frontmatter-only] [--json]
varde-docs concept update   --bundle <dir> <slug> --expected-version <hash> [--file <path>] [--json]
varde-docs concept set-field --bundle <dir> <slug> <key> <value> --expected-version <hash> [--json]
varde-docs concept delete   --bundle <dir> <slug> [--json]
varde-docs concept list     [--bundle <dir>] [--vault personal|project] [--include-deprecated] [--json]
varde-docs concept search   [--field key=value]... [--text <query>] [--limit <n>] [--bundle <dir>] [--vault personal|project] [--json]
varde-docs lint             [--bundle <dir>] [--vault personal|project] [--okf] [--json]
```

`search` composes two modes: `--field key=value` (repeatable, exact
frontmatter AND-match) narrows first, then `--text <query>` ranks the
remainder with lexical full-text search over bodies and frontmatter values
(`--limit` caps results). `lint` runs spec-agnostic structural checks by
default; `--okf` adds OKF v0.2 checks. Neither lint mode ever blocks a write.

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

## Fallback rule

If any `varde-docs` call fails for any reason, fall back immediately to
Read/Write/Edit/Grep for that one operation — don't block on it or try to
build/install it yourself. Absence of the binary is not an error.
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

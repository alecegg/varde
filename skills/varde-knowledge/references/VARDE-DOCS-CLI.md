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
## Operations

The knowledge bundle root is `memory-bank/knowledge/`; a note's slug is its
type-first path minus the `.md` suffix (e.g. `pattern/code-review`). Every
by-hand operation in this skill has a CLI equivalent — use it when
`varde-docs` is present, otherwise use the plain-file flow described in the
skill body.

```bash
BUNDLE=memory-bank/knowledge

# Find candidate notes — ranked full-text over bodies + frontmatter, instead
# of a manual grep sweep. --field narrows by frontmatter first when useful.
varde-docs concept search --bundle "$BUNDLE" --text "<query>" --limit 10 --json
varde-docs concept search --bundle "$BUNDLE" --field type=decision --text "<query>" --json

# Read one note (frontmatter + body + the version hash needed to write it).
varde-docs concept show --bundle "$BUNDLE" <type>/<slug> --json

# Create a new note. Write the full markdown (frontmatter + body) to a temp
# file first — the same content the skill body specifies (type, description,
# generated, etc.).
varde-docs concept create --bundle "$BUNDLE" <type>/<slug> --file "${TMPDIR:-/tmp}/note.md"

# Edit an existing note conflict-safely: show → read its "version" from the
# JSON → edit → update with that hash. On exit 3, re-show and reconcile before
# retrying (see the OCC contract).
varde-docs concept show --bundle "$BUNDLE" <type>/<slug> --json   # note the "version" value
varde-docs concept update --bundle "$BUNDLE" <type>/<slug> --expected-version <version> --file "${TMPDIR:-/tmp}/note.md"

# Retire a note — prefer the status field over deletion (OKF §5.4).
varde-docs concept set-field --bundle "$BUNDLE" <type>/<slug> status deprecated --expected-version "$HASH"

# Health check: structural by default, --okf adds OKF v0.2 spec checks.
varde-docs lint --bundle "$BUNDLE" --json
varde-docs lint --bundle "$BUNDLE" --okf --json
```

Notes:

- **This does not change the note conventions** in the skill body — type-first
  paths, required `type`/`description`/`generated` frontmatter, markdown
  (not wiki-) links, reserved `index.md`/`log.md`. The CLI is a safer
  read/write path for the same files, not a different format.
- `search --text` replaces the `grep -ril` sweep with ranked results; still
  `show` (or Read) the full note before acting on it.
- Prefer `update`/`set-field` over Edit when the binary is present: the OCC
  hash prevents clobbering a concurrent edit (e.g. a user editing the same
  note). Fall back to Edit on any failure.

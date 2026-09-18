# Optional `varde-docs` CLI

`varde-docs` is an optional Rust command-line tool on PATH. It manages
Markdown with frontmatter, safe concurrent writes, project and personal
stores, full-text search, and optional linting. Prefer it for safe writes and
ranked search. Check once per session:

```bash
command -v varde-docs >/dev/null 2>&1
```

Absent, ignore this file and use plain Read/Write/Edit/Grep/Glob for the same
operations. Do not build or install it; its absence is not an error.

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

## Documentation refresh

Refresh uses two bundles. Paths are relative to `repoRoot`.

**Generated specs (read):** When refreshing spec-declared sections (Phase 0)
and proposing edits, read the specs bundle instead of Grep/Read:

```bash
varde-docs concept show   --bundle memory-bank/knowledge specs/<domain> --json
varde-docs concept search --bundle memory-bank/knowledge --field type=spec --text "<query>" --json
```

**README + `docs/*.md` (read/write).** README.md is slug `README` in bundle
`.`; a doc `docs/foo.md` is slug `foo` in bundle `docs`.

```bash
# Discovery / drift hunt (Phase 1, Phase 3): ranked full-text instead of a
# manual read of every doc/source pair.
varde-docs concept search --bundle docs --text "<feature/term>" --json
varde-docs concept show   --bundle docs foo --json    # whole doc + "version"

# Whole-file write (a full-doc regenerate or an approved proposal): OCC update.
varde-docs concept update --bundle docs foo --expected-version <version> --file "${TMPDIR:-/tmp}/doc.md"
```

Caveats:

- **Section-scoped rewrites stay Edit.** The auto-generate track rewrites only
  the blocks inside a freshness marker; the CLI writes at whole-file
  granularity and can't touch just one marked section. Use the CLI for
  whole-doc `show`/`search` and full-file writes; keep Edit for in-place
  marker-block rewrites (`references/refresh-phase-2-autogenerate.md`).
- **Plain docs may have no frontmatter** — that's fine (`create` requires no
  `type`; OCC hashes the whole file). `--field`/`lint` just have less to work
  with on frontmatter-less docs; `--text` search still applies.
- **OCC clobber-protection is load-bearing in the default checkout.** Since
  this skill usually runs in the current checkout (not a worktree), a
  concurrent edit is possible — the `--expected-version` check catches it. Its
  other wins are ranked `search` discovery and uniform whole-doc reads.

## Spec generation

Spec documents are notes in `memory-bank/knowledge/`, one domain per file
under `specs/`, with slug `specs/<domain>`. Use `varde-docs` for these writes.
On failure, use Write, Edit, or `git rm`. Paths are relative to `repoRoot`.

```bash
BUNDLE=memory-bank/knowledge

# Step 3 (per-domain agents): write each domain doc. First run of a domain is
# a create; a refresh is an OCC update (show → read "version" → update).
varde-docs concept create --bundle "$BUNDLE" specs/<domain> --file "${TMPDIR:-/tmp}/spec.md"
varde-docs concept show   --bundle "$BUNDLE" specs/<domain> --json   # note "version"
varde-docs concept update --bundle "$BUNDLE" specs/<domain> --expected-version <version> --file "${TMPDIR:-/tmp}/spec.md"

# Existing specs, to scope refresh/orphan checks.
varde-docs concept list --bundle "$BUNDLE" --field type=spec --json

# Step 4 (orphans): delete a domain whose code no longer exists. Exit 2
# (not found) means it's already gone — treat as done, not an error.
varde-docs concept delete --bundle "$BUNDLE" specs/<domain>

# Step 6 (verify): structural checks; --okf adds OKF v0.2 checks. Reports
# broken links / malformed frontmatter without blocking.
varde-docs lint --bundle "$BUNDLE" --json
```

Caveats:

- **`specs/index.md` stays a plain Write.** `index.md` is a reserved bundle
  filename the CLI treats as bookkeeping, not a concept — keep writing it
  deterministically (step 5) with Write, never `concept create`.
- **Within the worktree, OCC is belt-and-suspenders** — each domain agent
  writes a distinct file and the run is already isolated. The reason to use
  the CLI here is uniform create/update/delete/lint and consistency with the
  knowledge bundle, not clobber-protection.
- The spec **format and frontmatter** (`type: spec`, etc.) are unchanged —
  see `references/spec-format.md`; the CLI writes the same files.

## Fallback rule

If the sandbox denies access to a path outside the workspace — the Personal
vault under `~/.varde-docs/`, or a lock beside it — retry that call once with
escalated filesystem access, keeping the command unchanged. If approval is
unavailable, denied, or the retry fails, use Read/Write/Edit/Grep for that
operation and name the degraded capability in your next message.

On any other failure, fall back to Read/Write/Edit/Grep for that one operation
— don't block on it or try to build/install it yourself. An absent binary is
not an error and needs no report.

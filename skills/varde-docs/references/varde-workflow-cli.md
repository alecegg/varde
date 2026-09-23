# Optional `varde-workflow` CLI

`varde-workflow` is an optional Rust command-line tool on PATH. It manages
Markdown with frontmatter, safe concurrent writes, project and personal
stores, full-text search, and optional linting. Prefer it for safe writes and
ranked search. Check once per session:

```bash
command -v varde-workflow >/dev/null 2>&1
```

If unavailable, continue with plain reads and searches; those operations are
degraded.
Stop before CLI-owned mutations. Use CLI whole-artifact commands.

## Decision rule

- **Known content:** Read one known artifact directly when no mutation follows.
- **Discovery:** Search unknown candidates. Use list or maps for inventories.
- **Mutation:** Use state commands when applicable. Use OCC concept writes.
- **Output scope:** Use text for reading. Request JSON for required fields.
- **Candidate reads:** Search first. Show only selected concepts.

## Vocabulary map

Use these CLI terms for the artifacts this skill already manages:

- **Concept** = one markdown file with YAML frontmatter (a knowledge note, a
  plan doc, any `<slug>.md`).
- **Slug** = the file's bundle-root-relative path, `/`-separated, `.md`
  stripped, kebab-case segments. A nested file
  `<knowledge>/pattern/code-review.md` under bundle root
  `<knowledge>/` has slug `pattern/code-review`.
- **Bundle** = a directory tree of concept `.md` files, passed as
  `--bundle <dir>`. Walks recurse at any depth.
- **Vault** = the Personal (`~/.varde-workflow/`) vs Project (a repo bundle)
  layering that `list`/`search`/`lint` merge by default (Project wins on a
  same-slug collision); `--vault personal|project` narrows to one side.

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

## Documentation refresh

Refresh uses two bundles. Paths are relative to `repoRoot`.

**Generated specs (read):** Search when the relevant domain is unknown. Read a
known spec directly unless an OCC write follows:

```bash
varde-workflow concept search --bundle <knowledge> --field type=spec --text "<query>"
```

**README + `docs/*.md` (read/write).** README.md is slug `README` in bundle
`.`; a doc `docs/foo.md` is slug `foo` in bundle `docs`.

```bash
# Discovery / drift hunt (Phase 1, Phase 3): ranked full-text instead of a
# manual read of every doc/source pair.
varde-workflow concept search --bundle docs --text "<feature/term>"
varde-workflow concept show   --bundle docs foo --json    # whole doc + "version"

# Whole-file write (a full-doc regenerate or an approved proposal): OCC update.
varde-workflow concept update --bundle docs foo --expected-version <version> --file "${TMPDIR:-/tmp}/doc.md"
```

Caveats:

- **Section-scoped rewrites stay Edit.** The auto-generate track rewrites only
  the blocks inside a freshness marker; the CLI writes at whole-file
  granularity and can't touch just one marked section. Use the CLI for
  whole-doc `show`/`search` and full-file writes; keep Edit for in-place
  marker-block rewrites (`references/refresh-phase-2-autogenerate.md`).
- **Plain docs can omit frontmatter.** `create` requires no `type`, and OCC
  hashes the whole file. `--field` and `lint` have less data to inspect on
  frontmatter-less docs; `--text` search still applies.
- **OCC protects current-checkout edits.** Since this skill usually runs in the
  current checkout, a concurrent edit is possible. The `--expected-version`
  check catches it. OCC also provides ranked `search` and consistent whole-doc
  reads.

## Spec generation

Spec documents are notes in `<knowledge>/`, one domain per file
under `specs/`, with slug `specs/<domain>`. Use `varde-workflow` for these
writes. On failure, preserve bytes and stop. Paths are relative to `repoRoot`.

```bash
BUNDLE=<knowledge>

# Step 3 (per-domain agents): write each domain doc. First run of a domain is
# a create; a refresh is an OCC update (show → read "version" → update).
varde-workflow concept create --bundle "$BUNDLE" specs/<domain> --file "${TMPDIR:-/tmp}/spec.md"
varde-workflow concept show   --bundle "$BUNDLE" specs/<domain> --json   # note "version"
varde-workflow concept update --bundle "$BUNDLE" specs/<domain> --expected-version <version> --file "${TMPDIR:-/tmp}/spec.md"

# Existing specs, to scope refresh/orphan checks.
varde-workflow concept search --bundle "$BUNDLE" --field type=spec

# Step 4 (orphans): delete a domain whose code no longer exists. Exit 2
# (not found) means it's already gone — treat as done, not an error.
varde-workflow concept delete --bundle "$BUNDLE" specs/<domain>

# Step 6 (verify): structural checks; --okf adds OKF v0.2 checks. Reports
# broken links / malformed frontmatter without blocking.
varde-workflow lint --bundle "$BUNDLE"
```

Caveats:

- **`specs/index.md` stays a plain Write.** `index.md` is a reserved bundle
  filename the CLI treats as bookkeeping, not a concept — keep writing it
  deterministically (step 5) with Write, never `concept create`.
- **Within a worktree, OCC adds no collision protection.** Each domain agent
  writes a distinct file and the run is already isolated. Use the CLI here for
  consistent create/update/delete/lint operations and knowledge-bundle access.
- The spec **format and frontmatter** (`type: spec`, etc.) are unchanged —
  see `references/spec-format.md`; the CLI writes the same files.

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

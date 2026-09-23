# Optional `varde-workflow` CLI

`varde-workflow` is an optional Rust command-line tool on PATH. It manages
Markdown with frontmatter, safe concurrent writes, project and personal
stores, full-text search, and optional linting. Prefer it for safe writes and
ranked search. Check once per session:

```bash
command -v varde-workflow >/dev/null 2>&1
```

If it is unavailable, use plain reads and searches and report the missing CLI as
a degraded capability.
Stop before CLI-owned mutations. Use CLI concept commands.

## Decision rule

- **Known content:** Read one known artifact directly when no mutation follows.
- **Discovery:** Search unknown candidates. Use list or maps for inventories.
- **Mutation:** Use state commands when applicable. Use OCC concept writes.
- **Output scope:** Use text for reading. Request JSON for required fields.
- **Candidate reads:** Search first. Show only selected concepts.

## Vocabulary map

The CLI's OKF vocabulary maps onto the artifacts these skills already manage:

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

## Operations

The knowledge root is `<knowledge>/`. A note's slug is its
type-first path without `.md`, such as `pattern/code-review`. Use
`varde-workflow` when available. Otherwise follow the plain-file steps.

```bash
BUNDLE=<knowledge>

# Find candidate notes — ranked full-text over bodies + frontmatter, instead
# of a manual grep sweep. --field narrows by frontmatter first when useful.
varde-workflow concept search --bundle "$BUNDLE" --text "<query>" --limit 10
varde-workflow concept search --bundle "$BUNDLE" --field type=decision --text "<query>"

# Before mutation, read content and its required version once.
varde-workflow concept show --bundle "$BUNDLE" <type>/<slug> --json

# Create a new note. Write the full markdown (frontmatter + body) to a temp
# file first — the same content the skill body specifies (type, description,
# generated, etc.).
varde-workflow concept create --bundle "$BUNDLE" <type>/<slug> --file "${TMPDIR:-/tmp}/note.md"

# Edit an existing note conflict-safely: show → read its "version" from the
# JSON → edit → update with that hash. On exit 3, re-show and reconcile before
# retrying (see the OCC contract).
varde-workflow concept show --bundle "$BUNDLE" <type>/<slug> --json   # note the "version" value
varde-workflow concept update --bundle "$BUNDLE" <type>/<slug> --expected-version <version> --file "${TMPDIR:-/tmp}/note.md"

# Retire a note — prefer the status field over deletion (OKF §5.4).
varde-workflow concept set-field --bundle "$BUNDLE" <type>/<slug> status deprecated --expected-version "$HASH"

# Health check: structural by default, --okf adds OKF v0.2 spec checks.
varde-workflow lint --bundle "$BUNDLE"
varde-workflow lint --bundle "$BUNDLE" --okf
```

Notes:

- **This does not change the note conventions** in the skill body — type-first
  paths, required `type`/`description`/`generated` frontmatter, markdown
  (not wiki-) links, reserved `index.md`/`log.md`. The CLI is a safer
  read/write path for the same files, not a different format.
- `search --text` replaces the `grep -ril` sweep with ranked results; still
  `show` (or Read) the full note before acting on it.
- Use `update` or `set-field` for every mutation.
- On failure, preserve bytes and report the blocker.

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

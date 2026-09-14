# Optional varde-code CLI

`varde-code` is a standalone, pre-alpha Rust CLI installed on PATH as
`varde-code` (CLI-only — no MCP server surface). It's optional: use it when
available and fall back to plain Read/Grep/Glob when it isn't. Check once
per session whether it's installed:

```bash
command -v varde-code >/dev/null 2>&1
```
If `varde-code` is not installed, ignore this file entirely and use the plain
Read/Grep workflow described elsewhere in this skill. Do not build or
install it, and don't treat its absence as an error — it's pre-alpha and
may not exist in a given checkout.

When `varde-code` is set, prefer it over `Read`/`Grep`/`Glob` for anything it
can answer — that's the point of using it (fewer tokens, no manual file
walking). Fall back to `Read` per-file only for content the CLI can't
supply (comments/prose context around a symbol, non-code files, or when a
query errors).

## Build before query

Every query subcommand reads from a persisted index. Run `build` once per
session (not before every query — it does a full rebuild each time):

```bash
varde-code build --repo-root "$(pwd)"
```

## Diffing since the last run

`source_commit` (the sha recorded in `specs/index.md` frontmatter after the
prior run) is the watermark. Use `detect_changes` instead of a manual
directory scan or `git diff --name-only` to find what actually needs
rereading:

```bash
varde-code detect_changes --json '{"repoRoot": "'"$(pwd)"'", "diffMode": "range", "range": "'"$SOURCE_COMMIT"'..HEAD"}'
```

Returns the symbols that changed between the two git states — this is the
whole basis for scoping SPEC-PLAN.md's dirty-domain pass: map each changed
symbol's `file` to a domain (via `map_file`/`clusters`, below) and only
those domains are `dirty`. No `source_commit` (first run) → skip this and
fall back to a full scan.

## Reading symbol content (replaces Read for domain generation)

```bash
# Full symbol list + source body for a file — the primary substitute for
# Read when authoring/updating a domain document's Key Operations, Key
# Types, and Invariants sections.
varde-code symbols_in_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts", "includeBody": true}'

# Same, batched across every file in a domain's scope in one call.
varde-code symbols_in_files --json '{"repoRoot": "'"$(pwd)"'", "filePaths": ["src/foo.ts", "src/bar.ts"], "includeBody": true}'

# One named symbol, optionally scoped to a file/kind.
varde-code get_symbol --json '{"repoRoot": "'"$(pwd)"'", "name": "createUser", "includeBody": true}'

# Covering tests for an Acceptance Criteria "Verified by" note (SPEC-FORMAT.md)
varde-code tests_for_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
```

`includeBody: true` returns the actual source text per symbol — this is
what makes CLI-first generation possible, not just discovery. Only reach
for `Read` on a file when: the CLI errors on it, the content needed isn't
a symbol (e.g. module-level prose/comments, config, markdown), or the
symbol list doesn't resolve what's needed.

## Discovery and graph operations

```bash
# Keyword/feature-area discovery — replaces a manual Grep/Glob sweep when the
# spec target is a keyword rather than a known path. Matches files, directory
# names, and symbol names, plus their one-hop neighborhood and covering
# tests. Structural only (no doc corpus, no semantic search).
varde-code context_pack --json '{"repoRoot": "'"$(pwd)"'", "query": "authentication"}'

# Community-detection clustering of the resolution graph into densely
# interconnected file groups — a data-backed starting point for the
# domain-boundary judgment in SPEC-PLAN.md's step 2, instead of reading
# code structure manually to decide domain grouping.
varde-code clusters --json '{"repoRoot": "'"$(pwd)"'"}'

# Dependency graph feeding spec regeneration
varde-code dependencies --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code dependents --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Map a file or symbol to its persisted node info (complexity, churn,
# fan-in/out, community) — used to bucket a detect_changes result into
# domains.
varde-code map_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code map_symbol --json '{"repoRoot": "'"$(pwd)"'", "name": "createUser"}'

# Multiple query modes in one call — use to batch a domain's map_file +
# symbols_in_file + dependencies lookups instead of N separate invocations.
varde-code batch --json '{"repoRoot": "'"$(pwd)"'", "calls": [...]}'
```

All commands print a uniform envelope: `{"ok": true, "data": ...}` or
`{"ok": false, "error": {...}}`.

## Fallback rule

If any `varde-code` call fails for any reason (binary missing, build
stale, unexpected error), fall back immediately to reading the relevant
files directly for that file/domain only — don't abandon CLI usage for the
rest of the run. Don't block on it or try to build/install it yourself.
A CLI call that *succeeds* but looks wrong (empty/implausible result) is
not a failure — spot-check it against one real file with `Read` before
trusting it for planning; don't silently propagate a bad result into the
dirty-domain list.

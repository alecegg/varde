# Optional `varde-code` CLI

An optional Rust CLI on PATH. If `command -v varde-code` finds nothing, ignore
this file and use Read/Grep/Glob — not an error, and never build or install it
yourself. Index once per session first:

```bash
varde-code build --repo-root "$(pwd)"   # full rebuild each time
```

Every command prints `{"ok": true, "data": ...}` or `{"ok": false, "error": {...}}`.

## Diffing since the last run

Work from a watermark instead of rescanning. For a refresh, the watermark is a
marker's `source_hash` (`references/refresh-marker-format.md`); for spec
generation, it is the `source_commit` recorded in `specs/index.md` frontmatter.

```bash
varde-code detect_changes --json '{"repoRoot": "'"$(pwd)"'", "diffMode": "range", "range": "'"$WATERMARK"'..HEAD"}'
```

It returns the symbols that changed between the two git states.

- **Refresh:** If no returned symbol touches a doc's declared sources, that
  section is up to date — skip it without opening the doc/source pair. Only
  sections whose sources appear in the diff join the stale set.
- **Spec:** Map each changed symbol's `file` to a domain (via `map_file` or
  `clusters`, below); only those domains are `dirty`. This is the whole basis
  for scoping the dirty-domain pass in `references/spec-plan.md`.

If the watermark is not a resolvable git ref — a first run, or a description
string rather than a sha — skip this and fall back to a full comparison.

## Reading symbol content

This replaces `Read` when rewriting a stale marker-declared block or authoring a
domain document's Key Operations, Key Types, and Invariants sections.

```bash
varde-code symbols_in_file  --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts", "includeBody": true}'
varde-code symbols_in_files --json '{"repoRoot": "'"$(pwd)"'", "filePaths": ["src/foo.ts", "src/bar.ts"], "includeBody": true}'
varde-code get_symbol       --json '{"repoRoot": "'"$(pwd)"'", "name": "createUser", "includeBody": true}'

# Covering tests for an Acceptance Criteria "Verified by" note
varde-code tests_for_file   --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
```

`includeBody: true` returns the actual source text per symbol — that is what
makes CLI-first generation possible, not just discovery. Reach for `Read` only
when the CLI errors, the content is not a symbol, or the symbol list does not
resolve what is needed.

## Discovery and graph operations

```bash
# Match a keyword or unmarked doc to its likely source or domain
varde-code context_pack --json '{"repoRoot": "'"$(pwd)"'", "query": "authentication"}'

# Community-detection clustering into densely interconnected file groups — a
# data-backed starting point for the domain-boundary judgment in spec planning
varde-code clusters     --json '{"repoRoot": "'"$(pwd)"'"}'

varde-code dependencies --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code dependents   --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Map a file or symbol to its persisted node info (complexity, churn,
# fan-in/out, community) — used to bucket a detect_changes result into domains
varde-code map_file     --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code map_symbol   --json '{"repoRoot": "'"$(pwd)"'", "name": "createUser"}'

# Batch a domain's map_file + symbols_in_file + dependencies in one invocation
varde-code batch        --json '{"repoRoot": "'"$(pwd)"'", "calls": [...]}'
```

## Fallback rule

If the sandbox denies access to an index or lock under `~/.config/varde-code/`,
retry that call once with escalated filesystem access, keeping the command
unchanged. If approval is unavailable, denied, or the retry fails, use Read/Grep
for that lookup and name the degraded capability in your next message.

On any other failure, fall back to Read/Grep for that one lookup and carry on
using the CLI for the rest of the run. A call that *succeeds* but looks
implausible — zero dependents for a symbol you know is exported — is not a
failure; spot-check with a targeted grep before trusting it.

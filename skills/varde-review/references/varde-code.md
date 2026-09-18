# Optional `varde-code` CLI

An optional Rust CLI on PATH. If `command -v varde-code` finds nothing, ignore
this file and use Read/Grep/Glob — not an error, and never build or install it
yourself. Index once per session first:

```bash
varde-code build --repo-root "$(pwd)"   # full rebuild each time
```

Every command prints `{"ok": true, "data": ...}` or `{"ok": false, "error": {...}}`.

## Review scoping

Additive to the grep step in `references/report-workflow.md`, not a replacement —
grep still runs for anti-pattern text matching. These add structural and graph
signal grep cannot produce, as a scoping pass before the manual read.

```bash
# Rank files by risk before deciding review depth
varde-code hotspots      --json '{"repoRoot": "'"$(pwd)"'"}'

# Blast radius of a changed file, and what depends on it
varde-code blast_radius  --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code dependents    --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Existing tests covering a changed file — an empty result is a CORRECTNESS
# severity signal (see `references/report-categories.md`)
varde-code tests_for_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Structural pattern shortlist with relational matching
varde-code find_pattern  --json '{"repoRoot": "'"$(pwd)"'", "pattern": "$FN($$$ARGS)", "file": "src/foo.ts", "inside": {"kind": "try_statement"}}'

# Batch across all changed files in the diff
varde-code batch         --json '{"repoRoot": "'"$(pwd)"'", "calls": [{"mode": "hotspots"}, {"mode": "blast_radius", "filePath": "src/foo.ts"}]}'

# Rule-pack findings over the persisted index — read-only, no --apply
varde-code scan          --json '{"repoRoot": "'"$(pwd)"'"}'
```

## Diff-scoped lookups

For a simplify pass, scope to what actually changed rather than the whole tree.

```bash
varde-code symbols_in_files --json '{"repoRoot": "'"$(pwd)"'", "filePaths": ["src/foo.ts", "src/bar.ts"], "includeBody": true}'
varde-code detect_changes   --json '{"repoRoot": "'"$(pwd)"'", "diffMode": "working"}'
```

`tests_for_file` (above) also scopes the verify run to the tests actually
covering an edited file, where the project's test runner supports targeting.

## Fallback rule

If the sandbox denies access to an index or lock under `~/.config/varde-code/`,
retry that call once with escalated filesystem access, keeping the command
unchanged. If approval is unavailable, denied, or the retry fails, use Read/Grep
for that lookup and name the degraded capability in your next message.

On any other failure, fall back to Read/Grep for that one lookup and carry on
using the CLI for the rest of the run. A call that *succeeds* but looks
implausible — zero dependents for a symbol you know is exported — is not a
failure; spot-check with a targeted grep before trusting it.

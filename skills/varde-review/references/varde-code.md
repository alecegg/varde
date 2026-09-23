# Optional `varde-code` CLI

`varde-code` is an optional Rust CLI on PATH. If
`command -v varde-code` finds nothing, use Read/Grep/Glob. Its absence is not
an error. Never build or install it yourself. When the decision below selects
the CLI, build its index once before other commands:

```bash
varde-code build --repo-root "$(pwd)"   # full rebuild each time
```

Every command prints `{"ok": true, "data": ...}` or `{"ok": false, "error": {...}}`.

## Decision rule

- **Discovery and relationships:** Use Varde Code for unknown scope,
  dependencies, tests, hotspots, and blast radius.
- **Known content:** Read short, located files directly.
- **Large known files:** Use `get_symbol` for one exact symbol.
- **Batch related lookups:** Build once, then batch related queries.
- **New or trivial targets:** Skip indexing.
- **Confirmation:** Confirm important CLI results against focused source reads.

## Review scoping

Additive to the grep step in `references/report.md`, not a replacement —
grep still runs for anti-pattern text matching. These add structural and graph
signal grep cannot produce, as a scoping pass before the manual read.

```bash
# Orient in an unfamiliar area before reading it — entrypoints, module
# layers, subsystems, and hotspots from the persisted index
varde-code nav_map       --json '{"repoRoot": "'"$(pwd)"'"}' --format text

# Rank files by risk before deciding review depth
varde-code hotspots      --json '{"repoRoot": "'"$(pwd)"'"}'

# Blast radius of a changed file, and what depends on it
varde-code blast_radius  --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code dependents    --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# How one file actually reaches another — the dependency path between them,
# for "does this change reach that subsystem" questions
varde-code map_path      --json '{"repoRoot": "'"$(pwd)"'", "sourceFile": "src/foo.ts", "targetFile": "src/bar.ts"}'

# Existing tests covering a changed file — an empty result is a CORRECTNESS
# severity signal (see `references/report-categories.md`)
varde-code tests_for_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Structural pattern shortlist with relational matching
varde-code find_pattern  --json '{"repoRoot": "'"$(pwd)"'", "pattern": "$FN($$$ARGS)", "file": "src/foo.ts", "inside": {"kind": "try_statement"}}'

# Batch across all changed files in the diff
varde-code batch         --json '{"repoRoot": "'"$(pwd)"'", "calls": [{"mode": "hotspots"}, {"mode": "blast_radius", "filePath": "src/foo.ts"}]}'

# Rule-pack findings; scan refreshes its index, without source rewrites
varde-code scan          --json '{"repoRoot": "'"$(pwd)"'"}'
```

For scan gates, inspect `ok` and `data.gate.status`.
Only `pass` exits zero; `fail` and `incomplete` exit nonzero.
Resolve diagnostics before treating an incomplete scan as certified.
The default `error` threshold gates every error rule, including exact-clone and
certified dependency policy. Architectural heuristics remain informational;
syntax rules declare language scopes. `gateRules` selects a nonempty set of
active rule IDs and excludes `severityThreshold`; boundary rules also require
configured prefixes.
Use `rules_list` to inspect active definitions and override provenance.
Read `references/scan.md` when triaging or customizing scan rules.

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

On any other failure, use Read/Grep for that lookup and keep using the CLI for
the rest of the run. If a successful result looks implausible, such as zero
dependents for an exported symbol, spot-check it with targeted grep before
trusting it.

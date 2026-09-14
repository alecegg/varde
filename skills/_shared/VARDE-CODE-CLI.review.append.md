If `varde-code` is not installed, ignore this file entirely and use the plain
grep/read workflow in `CODE-ANALYSIS.md` as-is. Do not build or install
it, and don't treat its absence as an error — it's pre-alpha and may not
exist in a given checkout.

## Build before query

Every query subcommand reads from a persisted index. Run `build` once per
review run (not before every query — it does a full rebuild each time):

```bash
varde-code build --repo-root "$(pwd)"
```

## Operations

Additive to `CODE-ANALYSIS.md`'s existing grep step, not a replacement —
grep still runs for anti-pattern text matching; these add structural and
graph signal grep can't produce, as a scoping pass before the manual read.

```bash
# Rank files by risk before deciding review depth
varde-code hotspots --json '{"repoRoot": "'"$(pwd)"'"}'

# Blast radius of a changed file — who's affected
varde-code blast_radius --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# What depends on a changed file
varde-code dependents --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Existing tests covering a changed file — empty result is a CORRECTNESS
# severity signal (CATEGORY-CORRECTNESS.md)
varde-code tests_for_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Structural pattern shortlist with relational matching
varde-code find_pattern --json '{"repoRoot": "'"$(pwd)"'", "pattern": "$FN($$$ARGS)", "file": "src/foo.ts", "inside": {"kind": "try_statement"}}'

# Batch across all changed files in the diff
varde-code batch --json '{"repoRoot": "'"$(pwd)"'", "calls": [{"mode": "hotspots"}, {"mode": "blast_radius", "filePath": "src/foo.ts"}]}'

# Rule-pack findings over the persisted index — read-only, no --apply
varde-code scan --json '{"repoRoot": "'"$(pwd)"'"}'
```

All commands print a uniform envelope: `{"ok": true, "data": ...}` or
`{"ok": false, "error": {...}}`.

## Fallback rule

If any `varde-code` call fails for any reason (binary missing, build
stale, unexpected error), fall back immediately to the plain grep/read
workflow in `CODE-ANALYSIS.md`. Don't block on it or try to build/install
it yourself.

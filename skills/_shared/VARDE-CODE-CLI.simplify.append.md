If `varde-code` is not installed, ignore this file entirely and use the plain
Read/Grep workflow described elsewhere in this skill. Do not build or
install it, and don't treat its absence as an error — it's pre-alpha and
may not exist in a given checkout.

## Build before query

Every query subcommand reads from a persisted index. Run `build` once per
session (not before every query — it does a full rebuild each time):

```bash
varde-code build --repo-root "$(pwd)"
```

## Operations

```bash
# Diff-scoped symbol lookup across the changed files, bodies included
varde-code symbols_in_files --json '{"repoRoot": "'"$(pwd)"'", "filePaths": ["src/foo.ts", "src/bar.ts"], "includeBody": true}'

# Symbols changed between git states — scope the pass to what actually changed
varde-code detect_changes --json '{"repoRoot": "'"$(pwd)"'", "diffMode": "working"}'

# Tests covering an edited file, to scope step 6's verify run instead of
# the whole suite (only where the project's test runner supports targeting)
varde-code tests_for_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
```

All commands print a uniform envelope: `{"ok": true, "data": ...}` or
`{"ok": false, "error": {...}}`.

## Fallback rule

If any `varde-code` call fails for any reason (binary missing, build
stale, unexpected error), fall back immediately to reading the relevant
files directly. Don't block on it or try to build/install it yourself.

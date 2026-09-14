# Optional varde-code CLI

`varde-code` is a standalone, pre-alpha Rust CLI installed on PATH as
`varde-code` (CLI-only — no MCP server surface). It's optional: use it when
available and fall back to plain Read/Grep/Glob when it isn't. Check once
per session whether it's installed:

```bash
command -v varde-code >/dev/null 2>&1
```
If `varde-code` is not installed, ignore this file entirely and use plain Read/Grep
as described in `EXECUTION.md`. Do not build or install it, and don't
treat its absence as an error — it's pre-alpha and may not exist in a
given checkout.

## Build before query

Every query subcommand reads from a persisted index. Run `build` once per
plan run (not before every query — it does a full rebuild each time):

```bash
varde-code build --repo-root "$(pwd)"
```

## Operations

Use these in place of a raw `Read` when establishing the **Given** section
of a task's execution frame (`EXECUTION.md`'s Given / Unknowns / Plan /
Verification), specifically for surveying files in a task's `modifies`
scope and pulling exact symbol bodies before a targeted edit.

```bash
# Survey a file's symbols before editing
varde-code symbols_in_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts", "includeBody": true}'

# Survey every file in a task's `modifies` list in one call
varde-code symbols_in_files --json '{"repoRoot": "'"$(pwd)"'", "filePaths": ["src/foo.ts", "src/bar.ts"], "includeBody": true}'

# Pull one symbol's exact body for a targeted edit — pass `body` straight
# into the edit tool's old-text argument, no second read needed
varde-code get_symbol --json '{"repoRoot": "'"$(pwd)"'", "name": "myFunction", "filePath": "src/foo.ts", "includeBody": true}'

# Multiple lookups sharing repoRoot/dbPath in one call
varde-code batch --json '{"repoRoot": "'"$(pwd)"'", "calls": [{"mode": "symbols_in_file", "filePath": "src/foo.ts"}, {"mode": "dependents", "filePath": "src/foo.ts"}]}'

# Existing tests covering a file, before writing a new one (TDD Cycle)
varde-code tests_for_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Symbol-level drift since the plan's authoring commit (Plan Staleness
# Check, Baseline Conflict Check) — more precise than a file-level git diff
varde-code detect_changes --json '{"repoRoot": "'"$(pwd)"'", "diffMode": "range", "range": "'"$PLAN_AUTHORING_COMMIT"'..HEAD"}'
```

All commands print a uniform envelope: `{"ok": true, "data": ...}` or
`{"ok": false, "error": {...}}`.

## Fallback rule

If any `varde-code` call fails for any reason (binary missing, build
stale, unexpected error), fall back immediately to reading the file
directly and grepping for the symbol, exactly as `EXECUTION.md` already
describes. Don't block on it or try to build/install it yourself.

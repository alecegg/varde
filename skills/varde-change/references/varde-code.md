# Optional `varde-code` CLI

An optional Rust CLI on PATH. If `command -v varde-code` finds nothing, ignore
this file and use Read/Grep/Glob — not an error, and never build or install it
yourself. Index once per session first:

```bash
varde-code build --repo-root "$(pwd)"   # full rebuild each time
```

Every command prints `{"ok": true, "data": ...}` or `{"ok": false, "error": {...}}`.

## Scoping a plan

Additive scoping signal for planning judgment calls — not a replacement for
reading the touched code. Use it to answer "what does this affect" before a
decomposition judgment call, not to author task content.

```bash
# External contract surface: who currently depends on a file or symbol the
# plan is about to change (`references/plan-fundamentals.md`)
varde-code dependents           --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code dependencies         --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code blast_radius         --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Wide-refactor scope: does a renamed or retyped symbol's blast radius fan
# across independent packages (→ expand/migrate/contract) or stay contained
# (→ normal vertical slice)? See `references/plan-acceptance-criteria.md`.
varde-code symbol_blast_radius  --json '{"repoRoot": "'"$(pwd)"'", "name": "SharedInterface"}'

# Keyword-driven discovery while growing the doc (`references/plan-grow-doc.md`)
varde-code context_pack         --json '{"repoRoot": "'"$(pwd)"'", "query": "authentication"}'

# Domain-boundary signal for splitting a plan into independently shippable
# candidates (`references/plan-splitting.md`) — a starting point, not a verdict
varde-code clusters             --json '{"repoRoot": "'"$(pwd)"'"}'

# Risk ranking: a change landing on a hotspot file gets a narrower slice
varde-code hotspots             --json '{"repoRoot": "'"$(pwd)"'"}'

# Existing type relationships an interface decision must honor
varde-code type_hierarchy       --json '{"repoRoot": "'"$(pwd)"'", "name": "MyClass"}'
```

## Executing a task

Use these in place of a raw `Read` when establishing the **Given** section of a
task's execution frame (`references/build-execution.md`) — surveying files in a
task's `modifies` scope and pulling exact symbol bodies before a targeted edit.

```bash
# Survey a file's symbols, or every file in a task's `modifies` list at once
varde-code symbols_in_file  --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts", "includeBody": true}'
varde-code symbols_in_files --json '{"repoRoot": "'"$(pwd)"'", "filePaths": ["src/foo.ts", "src/bar.ts"], "includeBody": true}'

# Pull one symbol's exact body for a targeted edit — pass `body` straight into
# the edit tool's old-text argument, no second read needed
varde-code get_symbol       --json '{"repoRoot": "'"$(pwd)"'", "name": "myFunction", "filePath": "src/foo.ts", "includeBody": true}'

# Existing tests covering a file, before writing a new one (TDD cycle)
varde-code tests_for_file   --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Symbol-level drift since the plan's authoring commit (plan staleness and
# baseline conflict checks) — more precise than a file-level git diff
varde-code detect_changes   --json '{"repoRoot": "'"$(pwd)"'", "diffMode": "range", "range": "'"$PLAN_AUTHORING_COMMIT"'..HEAD"}'

# Multiple lookups sharing repoRoot/dbPath in one call
varde-code batch            --json '{"repoRoot": "'"$(pwd)"'", "calls": [{"mode": "symbols_in_file", "filePath": "src/foo.ts"}, {"mode": "dependents", "filePath": "src/foo.ts"}]}'
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

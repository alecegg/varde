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
  dependencies, tests, and blast radius.
- **Known content:** Read short, located files directly.
- **Large known files:** Use `get_symbol` for one exact symbol.
- **Batch related lookups:** Build once, then batch related queries.
- **New or trivial targets:** Skip indexing.
- **Confirmation:** Confirm important CLI results against focused source reads.

## Scoping a plan

Additive scoping signal for planning judgment calls — not a replacement for
reading the touched code. Use it to answer "what does this affect" before a
decomposition judgment call, not to author task content.

```bash
# Orient before scoping an unfamiliar area — entrypoints, module layers,
# subsystems, and hotspots, so the plan's shape follows the repo's
varde-code nav_map              --json '{"repoRoot": "'"$(pwd)"'"}' --format text

# External contract surface: who currently depends on a file or symbol the
# plan is about to change (`references/plan-fundamentals.md`)
varde-code dependents           --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code dependencies         --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code blast_radius         --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Whether a change in one file can reach another at all — the dependency path
# between them, for splitting decisions that hinge on real coupling
varde-code map_path             --json '{"repoRoot": "'"$(pwd)"'", "sourceFile": "src/foo.ts", "targetFile": "src/bar.ts"}'

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

On any other failure, use Read/Grep for that lookup and keep using the CLI for
the rest of the run. If a successful result looks implausible, such as zero
dependents for an exported symbol, spot-check it with targeted grep before
trusting it.

## Impact evidence contract

Planning uses `dependents` for a direct consumer set and `blast_radius` for
transitive impact. After either query, read the important consumers and
relevant tests directly. Record the query and a short evidence summary in the
task's `#### Impact evidence` section.

For each confirmed consumer, add the exact
`impact:<repo-relative-path>` identifier to `verification_resources`. The
identifier is an opaque exact-match resource. Do not rewrite or infer it during
wave scheduling. If the CLI is unavailable, record the manually inspected
consumer paths and tests. Unresolved impact evidence disables parallel work.

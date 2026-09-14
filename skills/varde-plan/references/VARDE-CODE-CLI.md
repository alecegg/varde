# Optional varde-code CLI

`varde-code` is a standalone, pre-alpha Rust CLI installed on PATH as
`varde-code` (CLI-only — no MCP server surface). It's optional: use it when
available and fall back to plain Read/Grep/Glob when it isn't. Check once
per session whether it's installed:

```bash
command -v varde-code >/dev/null 2>&1
```
If `varde-code` is not installed, ignore this file entirely and use plain
Read/Grep/Glob for the same checks. Do not build or install it, and don't
treat its absence as an error.

```bash
varde-code build --repo-root "$(pwd)"   # once per session
```

## Operations

Additive scoping signal for planning judgment calls — not a replacement
for reading the touched code. Use it to answer "what does this affect"
before a human/task-decomposition judgment call, not to author task
content.

```bash
# External contract surface signal (PLAN-FUNDAMENTALS.md): who currently
# depends on a file/symbol the plan is about to change.
varde-code dependents --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code blast_radius --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code symbol_blast_radius --json '{"repoRoot": "'"$(pwd)"'", "name": "MySharedType"}'

# Wide-refactor scope signal (ACCEPTANCE-CRITERIA.md's shared-symbol check): does
# a renamed/retyped symbol's blast radius fan across independent packages
# (→ expand/migrate/contract) or stay contained (→ normal vertical slice)?
varde-code symbol_blast_radius --json '{"repoRoot": "'"$(pwd)"'", "name": "SharedInterface"}'

# "Expected files touched" for a task, when not already known from the
# plan's own research — a starting point for the executor, not a
# guarantee; the executor still confirms against the actual code at
# execution time.
varde-code dependents --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code dependencies --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Symbol content, when a research subagent needs to read what a shared
# symbol actually does rather than just where it's referenced.
varde-code get_symbol --json '{"repoRoot": "'"$(pwd)"'", "name": "createUser", "includeBody": true}'

# Keyword-driven discovery (GROW-DOC.md's research while growing the doc): turn a feature
# idea into relevant files/symbols instead of a manual grep/glob sweep.
varde-code context_pack --json '{"repoRoot": "'"$(pwd)"'", "query": "authentication"}'

# Domain-boundary signal for splitting a plan into independently shippable
# candidates (PLAN-SPLITTING.md) — a starting point to confirm/override,
# not a verdict.
varde-code clusters --json '{"repoRoot": "'"$(pwd)"'"}'

# Risk ranking for scope signals (ACCEPTANCE-CRITERIA.md) — a change landing on a
# hotspot file gets a narrower slice and more scrutiny.
varde-code hotspots --json '{"repoRoot": "'"$(pwd)"'"}'

# Existing type relationships an interface decision must honor
# (DESIGN-VOCABULARY.md's "Design It Twice").
varde-code type_hierarchy --json '{"repoRoot": "'"$(pwd)"'", "name": "MyClass"}'
```

All commands print a uniform envelope: `{"ok": true, "data": ...}` or
`{"ok": false, "error": {...}}`.

## Fallback rule

If any `varde-code` call fails for any reason, fall back immediately to
grep/read for that one check — don't block planning on it or try to
build/install it yourself. A call that succeeds but looks empty or
implausible (e.g. zero dependents for a symbol you know is exported) is
not a failure — spot-check with a targeted grep before treating a change
as contained.

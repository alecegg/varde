# Optional `varde-code` CLI

An optional Rust CLI on PATH. If `command -v varde-code` finds nothing, ignore
this file and use Read/Grep/Glob — not an error, and never build or install it
yourself. Index once per session first:

```bash
varde-code build --repo-root "$(pwd)"   # full rebuild each time
```

Every command prints `{"ok": true, "data": ...}` or `{"ok": false, "error": {...}}`.

## Operations

Treat every result as a focused reading list, then confirm the important
relationships against the actual source.

```bash
# Orient in an unfamiliar repository — start here
varde-code nav_map --json '{"repoRoot": "'"$(pwd)"'"}' --format text

# Gather the files, symbols, and covering tests around a concept or keyword
varde-code context_pack --json '{"repoRoot": "'"$(pwd)"'", "query": "authentication"}'

# Outgoing and incoming structural relationships for one file
varde-code dependencies --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code dependents --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Call graph from a seed file or symbol — direction outgoing, incoming, or both
varde-code explore --json '{"repoRoot": "'"$(pwd)"'", "query": {"params": {"input": "src/foo.ts", "direction": "both"}}}'

# Symbol body and type relationships, for writing an explanation
varde-code get_symbol --json '{"repoRoot": "'"$(pwd)"'", "name": "myFunction", "includeBody": true}'
varde-code type_hierarchy --json '{"repoRoot": "'"$(pwd)"'", "name": "MyClass"}'

# Size a candidate change before comparing alternatives
varde-code blast_radius --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code symbol_blast_radius --json '{"repoRoot": "'"$(pwd)"'", "name": "handle_request"}'

# Which tests would verify a given file
varde-code tests_for_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'

# Batch known lookups sharing one repository root
varde-code batch --json '{"repoRoot": "'"$(pwd)"'", "calls": [{"mode": "nav_map"}, {"mode": "dependents", "filePath": "src/foo.ts"}]}'
```

Pass `includeBody` only when source bodies are necessary, and
`includeReferences` only when usages are necessary.

## Fallback rule

If the sandbox denies access to an index or lock under `~/.config/varde-code/`,
retry that call once with escalated filesystem access, keeping the command
unchanged. If approval is unavailable, denied, or the retry fails, use Read/Grep
for that lookup and name the degraded capability in your next message.

On any other failure, fall back to Read/Grep for that one lookup and carry on
using the CLI for the rest of the run. A call that *succeeds* but looks
implausible — zero dependents for a symbol you know is exported — is not a
failure; spot-check with a targeted grep before trusting it.

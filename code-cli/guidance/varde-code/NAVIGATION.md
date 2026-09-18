# Code navigation

Use parsed symbols and resolved relationships for structural questions.
Use ordinary reads after identifying relevant source targets.

Start unfamiliar repository exploration with these commands:

```bash
varde-code nav_map --json '{"repoRoot":"<repo>"}' --format text
varde-code context_pack --json '{"repoRoot":"<repo>","query":"<concept>"}'
```

Choose commands from the question being answered:

- `symbols_in_file` surveys declarations inside one file.
- `get_symbol` retrieves one declaration and optional body.
- `dependencies` shows outgoing structural relationships.
- `dependents` shows direct incoming relationships.
- `explore` walks a bounded local dependency graph.
- `tests_for_file` finds likely affected tests.
- `find_pattern` searches parsed syntax without indexing.

Use repo-relative paths returned by earlier commands.
Pass `includeBody` only when source bodies are necessary.
Pass `includeReferences` only when usages are necessary.

Batch known lookups sharing one repository root:

```bash
varde-code batch --json '{"repoRoot":"<repo>","calls":[{"mode":"symbols_in_file","filePath":"src/server.rs"},{"mode":"dependents","filePath":"src/server.rs"}]}'
```

Every response uses an `ok` and `data` envelope.
Handle error envelopes before assuming zero query results.

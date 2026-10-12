# Change impact

Use impact commands before planning broad structural changes.

- `blast_radius` follows transitive file dependencies.
- `symbol_blast_radius` follows symbol-level relationships.
- `detect_changes` compares symbols across git states.
- `tests_for_file` identifies likely verification targets.
- `hotspots` highlights complex or frequently changed areas.

Examples:

```bash
varde map blast_radius --json '{"repoRoot":"<repo>","filePath":"src/server.rs"}'
varde map symbol_blast_radius --json '{"repoRoot":"<repo>","name":"handle_request"}'
varde map detect_changes --json '{"repoRoot":"<repo>","diffMode":"working"}'
varde map tests_for_file --json '{"repoRoot":"<repo>","filePath":"src/server.rs"}'
```

Treat output as a focused reading list.
Confirm important relationships against the actual source.

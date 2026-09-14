If `varde-code` is not installed, ignore this file entirely and use the plain
Read/Grep workflow described elsewhere in this skill. Do not build or
install it, and don't treat its absence as an error.

When `varde-code` is set, prefer it over `Read`/`Grep`/`Glob` for anything it
can answer. Fall back to `Read` per-file only for content the CLI can't
supply (prose/comments outside a symbol body, non-code files, or a query
that errors).

```bash
varde-code build --repo-root "$(pwd)"   # once per session
```

## Diffing since the last marker (Phase 1)

Each marker's `source_hash` (`references/MARKER-FORMAT.md`) is the
watermark for that doc's tracked sources. Before reading a marked doc's
sources in full, check whether they actually changed:

```bash
varde-code detect_changes --json '{"repoRoot": "'"$(pwd)"'", "diffMode": "range", "range": "'"$SOURCE_HASH"'..HEAD"}'
```

If `detect_changes` returns no symbols touching this doc's declared
sources, the section is up to date — skip it, don't open the doc/source
pair. Only sections whose sources appear in the diff go into Phase 2/3's
stale set. If `source_hash` isn't a resolvable git ref (e.g. it's a
description string, not a sha), fall back to reading the doc and source in
full to compare, as before.

## Reading symbol content (Phase 0 spec refresh, Phase 2 autogenerate)

```bash
# Content for the source(s) a marker-declared block maps to.
varde-code symbols_in_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts", "includeBody": true}'
varde-code symbols_in_files --json '{"repoRoot": "'"$(pwd)"'", "filePaths": ["src/foo.ts", "src/bar.ts"], "includeBody": true}'
varde-code get_symbol --json '{"repoRoot": "'"$(pwd)"'", "name": "createUser", "includeBody": true}'
```

`includeBody: true` returns actual source text per symbol — use this as
the primary content source when rewriting a stale marker-declared block,
instead of `Read`ing the whole source file.

## Discovery and graph operations (Phase 3 domain matching)

```bash
# Match an unmarked doc to its likely source/domain by name, instead of
# reading the tree to guess.
varde-code context_pack --json '{"repoRoot": "'"$(pwd)"'", "query": "planning and build"}'
varde-code clusters --json '{"repoRoot": "'"$(pwd)"'"}'
varde-code dependencies --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code dependents --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
varde-code map_file --json '{"repoRoot": "'"$(pwd)"'", "filePath": "src/foo.ts"}'
```

All commands print a uniform envelope: `{"ok": true, "data": ...}` or
`{"ok": false, "error": {...}}`.

## Fallback rule

If any `varde-code` call fails, fall back immediately to reading the
relevant files directly for that doc/source only — don't abandon CLI usage
for the rest of the run. A call that *succeeds* but looks wrong (empty or
implausible result) is not a failure — spot-check it against one real file
with `Read` before trusting it to mark a section up to date.

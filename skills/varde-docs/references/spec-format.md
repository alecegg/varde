<!-- kind: reference -->
# Specification document format

## Frontmatter and provenance

```yaml
type: spec
id: specs/<domain>
domain: <domain>
source_roots:
  - <repo-relative source file or directory>
covered_paths:
  - <repo-relative nonignored file beneath a source root>
source_hash: <aggregate over sources>
sources:
  - path: <repo-relative source path>
    hash: <git hash-object --no-filters <path>>
```

- `sources`: exactly the repo-relative files whose contents supplied generated
  output in this run, dropping paths not read this time. Each `hash` is the
  current blob hash, so working-tree edits register.
- `source_roots`: the domain boundary as repo-relative files and directories,
  without globs, excluding generated specs and other output so a spec never
  covers itself.
- `covered_paths`: the byte-sorted, unique inventory of existing nonignored
  files beneath those roots, contributing or not, including a file root
  itself. Build it from `git ls-files --cached --others --exclude-standard -z`
  at the repository root, discarding deleted paths.

### Computing `source_hash`

Run this from the repository root, passing the document's `sources` paths;
`varde-workflow` validates specs with this exact aggregate:

```bash
python3 <skill-dir>/scripts/source-hash.py -- <source-path>...
```

## Generated block

Every domain document has exactly one generated block, opening immediately
after the frontmatter:

```html
<!-- varde-spec:generated:start -->
...
<!-- varde-spec:generated:end -->
```

- Regenerate body content only between the sentinels.
- Preserve everything after the closing sentinel (the hand-authored
  `## Notes` tail) byte-identically, including whitespace and trailing
  newlines. Start a new document's tail as an empty `## Notes`.
- Treat a missing, duplicated, reversed, or unpaired sentinel as
  generated-boundary drift: leave the document unchanged and report it.

## Document content

Skeleton: `## Summary` / `## Overview` / `## Scope Boundary`
(owns|does-not-own) / `## Key Operations` / `## Key Types` / `## Invariants` /
`## Acceptance Criteria` / `## Flow: <name>`.

- Add an error-path table only when the flow has non-trivial failure handling
  (retries, partial writes, user-visible errors).
- Add flow-level GWT acceptance criteria only for behavior the domain-level
  Acceptance Criteria section does not already cover.
- The architecture document has only Overview, Components (each deployed or
  packaged unit and the domain spec owning its code), Wiring, Dependency
  Constraints, and Invariants; flows live in domain documents.

## Acceptance criteria

- Form: `Given <condition>, When <event>, Then <observable result>.`
- With `varde-code`, run `tests_for_file` on the domain's sources and note
  covering tests beside the list ("Verified by: `tests/foo.test.ts`"); omit
  the note when none exist.

## Index

`<knowledge>/specs/index.md`:

- links every domain document by its frontmatter domain, including
  architecture, and preserves hand-authored entries;
- has one frontmatter field, `source_commit: <git rev-parse HEAD at the end of
  this run>`, which scopes the next manual run;
- is rendered deterministically after domain generation and written only when
  its bytes differ.

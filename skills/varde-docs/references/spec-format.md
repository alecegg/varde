# Specification document format

Format for the domain documents, architecture document, and index under
`<knowledge>/specs/`.

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

`sources` is exactly the set of repo-relative files whose contents supplied
generated output in this run: drop paths not read this time, add new ones.
Each `hash` is the file's current blob hash, so working-tree edits register.

`source_roots` declares the domain boundary as repo-relative files and
directories, without globs. `covered_paths` is the byte-sorted, unique
inventory of all existing tracked and untracked, nonignored files beneath
those roots. Use `git ls-files --cached --others --exclude-standard -z` from
the repository root, discard deleted paths, and include a file root itself.
Choose roots that exclude generated specs and other output to avoid a spec
covering itself.
Record the inventory even when a file did not contribute to generated prose.
Added or removed files make the spec stale. A legacy document missing either
field is stale and must be regenerated. Report overlapping domain roots for
classification rather than silently assigning files to one domain.

### Computing `source_hash`

Sort the entries by `path` in byte order, concatenate each `path` immediately
followed by its `hash` (no separators, no trailing newline), and hash the
result as a blob. From the repository root, with the document's paths on
stdin:

```bash
source_hash=$(
  set -o pipefail
  LC_ALL=C sort | while IFS= read -r src_path; do
    src_hash=$(git hash-object --no-filters -- "$src_path") || exit 1
    printf '%s%s' "$src_path" "$src_hash"
  done | git hash-object --stdin
) || exit 1
printf '%s\n' "$source_hash"
```

`varde-workflow` validates specs with this exact aggregate. A document is
stale when any entry's hash, the aggregate, or the covered-path inventory
differs from a fresh recompute.
This per-document provenance is separate from the repository-wide
`source_commit` in `index.md`.

## Generated block

Every domain document has exactly one generated block, opening immediately
after the frontmatter:

```html
<!-- varde-spec:generated:start -->
...
<!-- varde-spec:generated:end -->
```

Update frontmatter provenance as specified above. Regenerate body content only
between the sentinels. Everything after the closing sentinel is the
hand-authored `## Notes` tail: preserve it byte-identically,
whitespace and trailing newlines included. A new document ends its generated
block with an empty `## Notes` tail. A missing, duplicated, reversed, or
unpaired sentinel is generated-boundary drift: leave the document unchanged
and report it.

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
  Constraints, and Invariants; flows live in domain documents. A plan's
  `observed_specs` may list `architecture`.

## Acceptance criteria

Write `Given <condition>, When <event>, Then <observable result>.` With
`varde-code`, run `tests_for_file` on the domain's sources and note covering
tests beside the list ("Verified by: `tests/foo.test.ts`"); omit the note when
none exist.

## Index

`<knowledge>/specs/index.md` lists every domain document by its frontmatter
domain, including architecture, with a link to each. Write it
deterministically after domain generation, preserving hand-authored entries.
Its only frontmatter field is `source_commit: <git rev-parse HEAD at the end
of this run>`; write it every run, with or without `varde-code`, so the next
run can scope incrementally from it.

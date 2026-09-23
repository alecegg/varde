# Specification document format

Format and generation-contract reference for the domain documents, architecture
document, and index written under `<knowledge>/specs/`.

## Document frontmatter

Each domain document uses this frontmatter:

```yaml
type: spec
id: specs/<domain>
domain: <domain>
source_hash: <hash over the document's sources>
sources:
  - path: <repo-relative source path>
    hash: <content hash of that source file>
```

`sources` lists every source file read for generated content. Compute each
entry's `hash` with `git hash-object <path>`, so working-tree edits register.
Compute `source_hash` deterministically: sort `sources` by `path`, concatenate
each `path` and `hash` pair in that order, then hash the resulting bytes with
`git hash-object --stdin`. The list and aggregate describe the exact inputs for
this document, not the repository-wide `source_commit` watermark in `index.md`.

## Generated block boundary and meaning layer

Every generated domain document has exactly one generated block. It starts
immediately after the frontmatter with this opening sentinel:

```html
<!-- varde-spec:generated:start -->
```

It ends with this closing sentinel:

```html
<!-- varde-spec:generated:end -->
```

During generation, replace only the bytes between the paired sentinels. Keep
everything below the closing sentinel as the hand-authored `## Notes` tail.
Preserve that Notes tail byte-identically across regeneration, including
whitespace and
trailing newlines. A new document ends its generated block, then starts an
empty `## Notes` tail for later hand-authored content.

## Legacy boundary migration

A legacy document has neither generated sentinel. On its first regeneration,
find the first top-level line whose complete content is `## Notes`. The exact
byte slice beginning with that line and continuing through EOF is its Notes
tail. Preserve that slice byte-for-byte, including its heading, whitespace,
and trailing newlines. Replace only the post-frontmatter bytes before that
slice with the new generated block and its paired sentinels. Later runs use
the sentinels normally.

A legacy document with no top-level `## Notes` heading has an ambiguous
hand-authored boundary: leave it unchanged and report generated-boundary drift.
A document with a missing, duplicated, reversed, or unpaired sentinel is boundary
drift too, not a migration candidate.

Mark a document migrated only after this check: take the exact byte slice from
the first `## Notes` line through EOF *before* regeneration, take the same slice
after, and assert that the SHA-256 digests match. Include trailing whitespace in
the slice.

The generated block contains exactly one document-level `## Summary` section.
Its plain-English text says what the domain does and how it connects. Related
domains use typed domain wikilinks in the form `[[domain:<domain>]]`. Each
target `<domain>` must be the domain name of another generated spec document.

Every `## Flow: <name>` section contains exactly one `### Crux` subsection.
The subsection names one cited source path, then presents the crux in a fenced
text block:

~~~~markdown
### Crux

Source: `<repo-relative path from sources>`

```text
<literal source substring>
```
~~~~

The named path must appear in this document's frontmatter `sources` list, and
the crux must be a literal, byte-for-byte substring of that file — copied out
whole, from one source. A crux captures a guard, skip condition, or state change
from the flow's source body, and appears inside `## Flow:` sections alone.

## Section provenance note

In each generated section, name the source files and symbols it uses, in prose
or a short list. For example: "Derived from `path/to/file.ts` (operations
`foo`, `bar`)". This lets readers trace the section to code. In flow sections,
also name the entry point or trigger when known.

## Section categories

Use these section categories:

- `scope-boundary`
- `key-ops`
- `invariants`
- `ac`
- `rules`

Omit `rules` when the domain has no rules. Rules appear inside domain documents —
they never get standalone files.

## Domain document structure

Domain documents contain Overview, Scope Boundary, Key Operations, Key Types,
Invariants, and Acceptance Criteria sections. Scope Boundary includes an
owns/does-not-own table. Key Operations and Key Types use tables. Acceptance
Criteria uses GWT bullets.

Each flow gets a `## Flow: <name>` section. Flow sections include the trigger,
steps, error-path table, and GWT acceptance criteria. Cross-domain flows link to
other domain docs.

The architecture document contains Overview, Layer Model, Dependency
Constraints, and Invariants only. Flows live in domain documents.

## Acceptance criteria format (GWT)

Flow and feature acceptance criteria use this form:

`Given <condition>, When <event>, Then <observable result>.`

When `varde-code` is available (`references/varde-code.md`), run `tests_for_file`
on the domain's source files. Note the covering test file(s) beside the AC list,
for example, "Verified by: `tests/foo.test.ts`". This lets readers trace a
claimed behavior to a running check. If no covering test exists, omit the note.

## Rule table format

Each rule table uses these columns:

`| Catches | Does not flag | Data source | Remediation |`

## Per-agent generation contract

Each domain agent receives the literal repository path, domain name, the
list of source files/directories that belong to that domain (from the plan
step), and — when the plan step detected `varde-code` — the CLI binary path
and the list of changed symbols/files scoped to this domain.

Content source, in order:

1. Read short, known files directly.
2. Batch Varde Code queries across several files or relationships.
3. Use `get_symbol` for exact symbols inside large files.
4. Use `Read`/`Grep`/`Glob` when Varde Code cannot supply content:
   module-level prose/comments outside a symbol body, non-code config, or
   any file where the CLI call errors.

Writes exactly one document: `<knowledge>/specs/<domain>.md` (the
architecture domain writes `<knowledge>/specs/architecture.md`).

Apply these constraints to each agent:

- Base the document only on what you read directly from this domain's source
  files during this run, staying inside the domain's boundary.
- Track every repo-relative source file whose contents supply generated
  output. Write `sources` from exactly that set using current content hashes,
  removing unread legacy paths and adding newly read paths before computing
  `source_hash`.
- For an existing document, read it first and apply a targeted edit to
  changed sections, preserving hand-authored sections.

## Index format

`<knowledge>/specs/index.md` lists domain names from each domain
document's frontmatter, includes architecture, and links to every domain
document. It contains no generated prose requiring an agent — write it
deterministically after domain generation finishes.

`index.md` must carry exactly one frontmatter field, `source_commit: <sha>`
(the `git rev-parse HEAD` at the end of this run) — used by the next run's
`detect_changes` diff (see `references/varde-code.md`). Write/overwrite it every
run, even when `varde-code` wasn't available this time, so the next run can
resume incremental scoping. It does not replace each document's `source_hash`
or `sources` provenance. No other frontmatter; it remains a directory listing
otherwise. Preserve hand-authored domain entries.

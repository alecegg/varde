# Spec document format

Format and generation-contract reference for the domain documents, architecture
document, and index written under `memory-bank/knowledge/specs/`.

## Document frontmatter

Each domain document uses this frontmatter:

```yaml
type: spec
id: specs/<domain>
domain: <domain>
```

## Section provenance note

Each generated section should note, in prose or a short list, which source
files/symbols it was derived from (e.g. "Derived from `path/to/file.ts`
(operations `foo`, `bar`)"), so a reader can trace the section back to the
code it describes. Flow sections may also note their entry point/trigger.

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
Constraints, and Invariants only — it contains no flow sections and must not add
architecture flows.

## Acceptance criteria format (GWT)

Flow and feature acceptance criteria use this form:

`Given <condition>, When <event>, Then <observable result>.`

When `varde-code` is available (`VARDE-CODE-CLI.md`), run `tests_for_file` on
the domain's source files and note the covering test file(s) alongside the
AC list (e.g. "Verified by: `tests/foo.test.ts`") — a reader can then trace
a claimed behavior to a real, running check rather than trusting prose
alone. Omit the note where no covering test exists; don't invent one.

## Rule table format

Each rule table uses these columns:

`| Catches | Does not flag | Data source | Remediation |`

## Per-agent generation contract

Each domain agent receives the literal repository path, domain name, the
list of source files/directories that belong to that domain (from the plan
step), and — when the plan step detected `varde-code` — the CLI binary path
and the list of changed symbols/files scoped to this domain.

Content source, in order:

1. If `varde-code` was passed in, call `symbols_in_files`/`get_symbol` with
   `includeBody: true` for this domain's files first — this is the primary
   way to read the domain's code for this run, not a supplement to Read.
2. Fall back to `Read`/`Grep`/`Glob` only for what the CLI can't supply:
   module-level prose/comments outside a symbol body, non-code config, or
   any file where the CLI call errors.

Writes exactly one document: `memory-bank/knowledge/specs/<domain>.md` (the
architecture domain writes `architecture.md`).

Constraints on each agent:

- Base the document only on what you read directly from the domain's source
  files during this run — do not invent content, and do not read unrelated
  source files outside the domain's boundary.
- For an existing document, read it first and apply a targeted edit to
  changed sections, preserving hand-authored sections.

## Index format

`memory-bank/knowledge/specs/index.md` lists domain names from each domain
document's frontmatter, includes architecture, and links to every domain
document. It contains no generated prose requiring an agent — write it
deterministically after domain generation finishes.

`index.md` carries exactly one frontmatter field, `source_commit: <sha>`
(the `git rev-parse HEAD` at the end of this run) — used by the next run's
`detect_changes` diff (see `VARDE-CODE-CLI.md`). Write/overwrite it every
run, even when `varde-code` wasn't available this time, so the next run can
resume incremental scoping. No other frontmatter; it remains a directory
listing otherwise. Preserve hand-authored domain entries.

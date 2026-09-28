---
type: reference
title: "Frontmatter field set & search — set-field / search / show --frontmatter-only"
---

# Frontmatter field set & search

How `varde-workflow` mutates and queries single frontmatter fields: the
generic OCC-guarded `concept set-field` verb, exact frontmatter filters
and ranked text search, `concept show --frontmatter-only`
structured retrieval, and the git-derived `created`/`updated` metadata in
`concept show`. Terminology follows `knowledge/definition/frontmatter-field`
and `knowledge/definition/extension-field`.

Every documented flag comes from the tool's own `--help` output.

## concept set-field

Set a single frontmatter key in place, OCC-guarded like the other write
verbs: `--expected-version` must match the file's current content hash or
the write is rejected as a conflict and the file is left untouched. This
is the sole canonical frontmatter-mutation verb — the former
deprecate/undeprecate commands are removed; set
`status` to `deprecated`, or `draft`, with this command.

```text
Usage: varde-workflow concept set-field [OPTIONS] --bundle <BUNDLE> --expected-version <EXPECTED_VERSION> <SLUG> <KEY> <VALUE>

Arguments:
  <SLUG>   Concept slug, e.g. `my-concept`
  <KEY>    Frontmatter key to set, e.g. `status`, `type`, or any extension key
  <VALUE>  New value; `status` is validated against `draft|stable|deprecated` and the structured §5/§10 fields reject bare-scalar writes

Options:
      --bundle <BUNDLE>
          Knowledge Bundle root directory (holds the Concept `.md` files)
      --expected-version <EXPECTED_VERSION>
          OCC version hash last read; a mismatch is rejected as a conflict
      --json
          Machine-readable JSON output
  -h, --help
          Print help
```

Validation rules (matching `md_core::crud::set_field`):

- `status` is a free-form string; any value is accepted, and removal
  (absent implies `stable`) is always allowed.
- `type` must be a non-empty string and can never be removed — it is the
  required identity field. Setting `type` on a Concept that lacks it
  repairs the Concept.
- The structured field names `sources`, `verified`, `generated`,
  `stale_after`, `runtime`, `executor`, `attester` reject a bare-scalar
  write: they are list/object-typed, and a scalar write would
  corrupt their YAML shape. (Removal is not exposed through this CLI verb,
  which always takes a value.)
- Any other key passes through unvalidated: producer-defined/extension
  fields are permitted and are written verbatim.

Text output on success:
`set <key>=<value> on <slug> (version <old> -> <new>)`.

JSON output on success:
`{ "slug", "key", "value", "old_version", "new_version" }`.

## concept search

Search the selected bundle trees on every invocation. `--field` matches
frontmatter values exactly. `--text` ranks lexical matches across slugs,
frontmatter, and bodies. Both options compose: fields narrow results first.
Search has no cached index or semantic matching.

```text
Usage: varde-workflow concept search [OPTIONS]

Options:
      --field <KEY=VALUE>
          Exact-value frontmatter filter `key=value`, repeatable; results must match every filter (AND semantics). Values match strings, the canonical form of other scalars, or any element of a sequence (e.g. `tags`)

      --text <QUERY>
          Rank lexical matches across Concept bodies and frontmatter

      --limit <N>
          Cap ranked text results (default: 20)

      --bundle <BUNDLE>
          Knowledge Bundle root directory (holds the Concept `.md` files). Defaults to the project's resolved `<knowledge>` directory (same resolution as `varde-workflow paths`) when omitted

      --json
          Machine-readable JSON output

  -h, --help
          Print help (see a summary with '-h')
```

Filter semantics:

- `--field key=value` is repeatable; an entry must match **every** filter
  (AND). A key absent from a Concept's frontmatter never matches.
- A YAML string matches when it equals the filter value; other scalars
  (`number`, `bool`) match their canonical string form (`42`, `true`); a
  sequence (e.g. `tags`) matches when any element matches; a mapping or
  null never matches.
- `type`, `status`, `tags`, and any custom/extension field are all
  filterable — there is no whitelist. Deprecated Concepts are **not**
  excluded by default: search returns everything matching the filters, and
  `--field status=deprecated` is how you find them.
- Bundle selection follows the same default as `list`/`lint`: `--bundle`
  when given, else the project's resolved `<knowledge>` directory. A
  missing bundle is an error.
- Unparseable frontmatter is a typed error. A missing `type` is allowed
  by ordinary search and is not flagged by `lint` either — no check
  requires a `type` field to be present.

With `--field` only, text output lists `slug<TAB>type`. JSON output
contains `slug`, `type`, and `frontmatter`. With `--text`, results are
ranked by score and include a short matching preview. `--limit` caps
ranked results. Ties sort by slug.

## concept show --frontmatter-only

`concept show` normally prints the frontmatter block, the body, then the
version. With `--frontmatter-only`, it prints only the parsed frontmatter
as structured JSON — no body text, no version line, no YAML. This is the
machine-consumable retrieval path matching the registry's contract.

```text
Usage: varde-workflow concept show [OPTIONS] --bundle <BUNDLE> <SLUG>

Options:
      --bundle <BUNDLE>   Knowledge Bundle root directory (holds the Concept `.md` files)
      --frontmatter-only  Print only the parsed frontmatter as structured JSON, omitting the body entirely (takes precedence over `--json`)
      --json              Machine-readable JSON output
  -h, --help              Print help
```

Example output: `{"type":"decision","title":"X"}`.

## created / updated (git-derived, read-only)

`concept show` surfaces two tool-derived metadata fields, computed at
read time from the Concept file's git history — **never** stored in or
read from frontmatter: `show`'s `created`/`updated` always come from
`git log`, and the tool never writes the derived values into frontmatter.
(A user-written `created`/`updated` frontmatter key is an ordinary
extension field: `set-field`/`search` treat it generically, and it is
never consulted for these timestamps.)

- `created` — the first commit's committer date.
- `updated` — the most recent commit's committer date.

Both are strict RFC 3339 strings. In text output they appear as
`created: <ts>` / `updated: <ts>` lines after `version:` only when a git
history exists; in `--json` output they are always present (`null` when
unknown). A bundle need not be version-controlled, so a
non-repo bundle, an untracked (never-committed) file, or a missing `git`
binary yields no timestamps — never an error, and `concept show` never
fails because of them.

## status semantics (folded in from the retired deprecation lifecycle doc)

`status` is a free-form string, not a fixed enum; absent implies
`stable`. `concept list` excludes `status: deprecated` Concepts by
default (a varde-workflow policy, not a validation rule); pass
`--include-deprecated` to include them. `status: draft`
Concepts are unaffected (still listed by default). `concept show` and
`concept delete` are unchanged by status: a deprecated Concept is still
shown, and delete hard-purges a live or deprecated Concept alike.

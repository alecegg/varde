---
type: reference
title: "varde-workflow CLI reference"
---

# varde-workflow CLI reference

Usage-only reference for the `varde-workflow` command-line tool. Every
documented flag comes from the tool's own `--help` output for that
subcommand. The tool reads and writes OKF v0.2 Concepts: one markdown file
per Concept (`<slug>.md`) holding a YAML frontmatter block with a required,
non-empty `type` field, plus a markdown body (OKF v0.2 §4).

## Global

```text
Usage: varde-workflow <COMMAND>

Commands:
  concept  Manage Concepts within a Knowledge Bundle
  lint     Lint a Knowledge Bundle for structural health issues
  help     Print this message or the help of the given subcommand(s)

Options:
  -h, --help     Print help
  -V, --version  Print version
```

- Every command takes an explicit, required `--bundle <PATH>` flag naming
  the Knowledge Bundle root directory — the directory holding the Concept
  `.md` files. There is no implicit directory walking.
- Output is human-readable text by default; the `--json` flag switches to
  machine-readable JSON output on every command.

## concept create

Create a Concept from a complete frontmatter+body document. The document
must carry a non-empty `type` field; the write fails without touching the
bundle when the slug already exists or the document is invalid. When
`--file` is used, the slug derives from the file's `<slug>.md` name; when a
positional `<SLUG>` is given instead, the document is read from stdin.

```text
Usage: varde-workflow concept create [OPTIONS] --bundle <BUNDLE> [SLUG]

Arguments:
  [SLUG]  Concept slug, e.g. `my-concept`; the document is read from stdin

Options:
      --bundle <BUNDLE>  Knowledge Bundle root directory (holds the Concept `.md` files)
      --file <FILE>      Read the concept document from this file; the slug derives from its `<slug>.md` filename
      --json             Machine-readable JSON output
  -h, --help             Print help
```

JSON output on success: `{ "slug": "<slug>", "version": "<16-hex-version>" }`
where `version` is the content hash of the written bytes.

## concept show

Show a Concept's frontmatter, body, and current version, plus the
git-derived `created`/`updated` metadata (see
`knowledge/reference/frontmatter-field-set-and-search`). When the slug is
missing from the bundle, the Personal Vault `~/.varde-workflow/` is
consulted before reporting not-found; see
`knowledge/reference/vault-layering-merge`. Exits non-zero with a
not-found error when no `<slug>.md` exists in the bundle.

```text
Usage: varde-workflow concept show [OPTIONS] --bundle <BUNDLE> <SLUG>

Arguments:
  <SLUG>  Concept slug, e.g. `my-concept`

Options:
      --bundle <BUNDLE>   Knowledge Bundle root directory (holds the Concept `.md` files)
      --frontmatter-only  Print only the parsed frontmatter as structured JSON, omitting the body entirely (takes precedence over `--json`)
      --json              Machine-readable JSON output
  -h, --help              Print help
```

Text output on success: the frontmatter block, the body, then
`version: <16-hex-version>`, with `created:` / `updated:` lines after it
when the Concept has git history. JSON output on success:
`{ "slug", "version", "frontmatter", "body", "created", "updated" }`
(`created`/`updated` are RFC 3339 strings, or `null` when unknown). With
`--frontmatter-only`, output is just the parsed frontmatter as structured
JSON, e.g. `{"type":"decision","title":"X"}` — no body, no version.

## concept update

Update a Concept, rejecting stale versions. The on-disk file's content hash
must equal `--expected-version <VERSION>` (the version last read, e.g. from
`concept show`); a mismatch is rejected with a conflict error and the file
is left unchanged. The new document is read from `--file` or stdin.

```text
Usage: varde-workflow concept update [OPTIONS] --bundle <BUNDLE> --expected-version <EXPECTED_VERSION> <SLUG>

Arguments:
  <SLUG>  Concept slug, e.g. `my-concept`

Options:
      --bundle <BUNDLE>
          Knowledge Bundle root directory (holds the Concept `.md` files)
      --expected-version <EXPECTED_VERSION>
          OCC version hash last read; a mismatch is rejected as a conflict
      --file <FILE>
          Read the new document from this file; the slug stays the same
      --json
          Machine-readable JSON output
  -h, --help
          Print help
```

JSON output on success: `{ "slug", "old_version", "new_version" }`.

## concept list

List the Concepts in the bundle, sorted by slug. Reserved bundle files
(`index.md`, `log.md`) and non-`.md` files are excluded (OKF v0.2 §3.1).
Concepts with `status: deprecated` are excluded by default; pass
`--include-deprecated` to include them (see
`knowledge/reference/frontmatter-field-set-and-search` for the `status`
semantics). An empty bundle prints `no concepts in bundle` and exits 0.

Since vault layering, the listing also merges in Concepts from the Personal
Vault `~/.varde-workflow/`; see `knowledge/reference/vault-layering-merge`.

```text
Usage: varde-workflow concept list [OPTIONS]

Options:
      --bundle <BUNDLE>
          Knowledge Bundle root directory (holds the Concept `.md` files). Without `--vault`, the listing merges this Project Vault with the Personal Vault by default; optional so `--vault` alone works
      --vault <VAULT>
          Narrow the listing to one vault: `personal` or `project`. Vault selection happens first; without it the default merges both vaults. With `--vault project`, a `--bundle` path is scanned as the project root (typically a subdirectory of it); with `--vault personal` a relative `--bundle` path filters within the fixed Personal Vault root (an absolute path has no additional effect)
      --include-deprecated
          Include `status: deprecated` Concepts in the listing
      --json
          Machine-readable JSON output
  -h, --help
          Print help (see a summary with '-h')
```

JSON output on success: `[ { "slug", "type" }, ... ]`.

## concept delete

Delete a Concept (hard delete): removes `<slug>.md` from the bundle. Exits
non-zero with a not-found error when the slug does not exist. Not
version-guarded — no `--expected-version` is required.

```text
Usage: varde-workflow concept delete [OPTIONS] --bundle <BUNDLE> <SLUG>

Arguments:
  <SLUG>  Concept slug, e.g. `my-concept`

Options:
      --bundle <BUNDLE>  Knowledge Bundle root directory (holds the Concept `.md` files)
      --json             Machine-readable JSON output
  -h, --help             Print help
```

JSON output on success: `{ "slug": "<slug>", "deleted": true }`.

## concept set-field

Set a single frontmatter key in place, rejecting stale versions — the
sole canonical frontmatter-mutation verb (the former
deprecate/undeprecate commands are removed). The write is OCC-guarded:
`--expected-version` must match the file's current content hash or the
write is rejected as a conflict and the file is left untouched. `status`
accepts only `draft | stable | deprecated`; `type` must be non-empty;
the structured §5/§10 fields (`sources`, `verified`, `generated`,
`stale_after`, `runtime`, `executor`, `attester`) reject bare-scalar
writes; any other key passes through unvalidated. See
`knowledge/reference/frontmatter-field-set-and-search`.

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

JSON output on success: `{ "slug", "key", "value", "old_version", "new_version" }`.

## concept search

Search Concepts by exact frontmatter field values, across whichever
bundles are selected (same `--bundle`/`--vault` matrix as `list`/`lint`;
both-vaults merge by default, Project Vault wins collisions). Repeatable
`--field key=value` filters with AND semantics; `type`, `status`, `tags`,
and any extension field are filterable. Exact-value matching only — no
substring/fuzzy/full-text search. See
`knowledge/reference/frontmatter-field-set-and-search`.

```text
Usage: varde-workflow concept search [OPTIONS]

Options:
      --field <KEY=VALUE>
          Exact-value frontmatter filter `key=value`, repeatable; results must match every filter (AND semantics). Values match strings, the canonical form of other scalars, or any element of a sequence (e.g. `tags`)
      --bundle <BUNDLE>
          Knowledge Bundle root directory (holds the Concept `.md` files). Without `--vault`, the search covers this Project Vault merged with the Personal Vault by default; optional so `--vault` alone works
      --vault <VAULT>
          Narrow the search to one vault: `personal` or `project`. Vault selection happens first; without it the default merges both vaults. With `--vault project`, a `--bundle` path is scanned as the project root (typically a subdirectory of it); with `--vault personal` a relative `--bundle` path filters within the fixed Personal Vault root (an absolute path has no additional effect)
      --json
          Machine-readable JSON output
  -h, --help
          Print help (see a summary with '-h')
```

Text output on success: one `slug<TAB>type` line per entry, or
`no concepts match` when empty. JSON output on success:
`[ { "slug", "type", "frontmatter" }, ... ]` where `frontmatter` is the
full parsed frontmatter object.

## lint

Run the contradiction-aware bundle_lint health check over a single
Knowledge Bundle — orphaned Concepts, broken bundle-internal links,
directories missing `index.md`, malformed Concept files, and unreadable
entries. Report-only: never modifies the bundle. See
`knowledge/reference/bundle-lint` for the checks, severities, traversal
scope, and exit-code contract.

```text
Usage: varde-workflow lint [OPTIONS] --bundle <BUNDLE>

Options:
      --bundle <BUNDLE>  Knowledge Bundle root directory (holds the Concept `.md` files)
      --json             Machine-readable JSON output
  -h, --help             Print help
```

Exits 0 when the report is empty or contains only warnings; exits non-zero
when any Error-severity issue exists. JSON output on success:
`[ { "severity", "check_kind", "path", "message" }, ... ]`.

## Errors

All commands exit 0 on success and non-zero on failure. Errors are printed
to stderr; in `--json` mode the error is printed as
`{ "error": "<message>" }` on stderr.

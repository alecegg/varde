---
type: reference
title: "bundle_lint — contradiction-aware health check"
---

# bundle_lint

`varde-workflow lint` runs the contradiction-aware health check over a
single Knowledge Bundle: it walks the bundle recursively (a
root-plus-subdirectories tree) and reports structural issues.
Report-only — it never modifies a bundle, never blocks
`create`/`update`/`delete`/`list`/`show`, and has no auto-fix. Terminology
follows `knowledge/definition/bundle-lint`; flag usage matches the CLI
reference `knowledge/reference/varde-workflow-cli`.

## Usage

```text
Usage: varde-workflow lint [OPTIONS]

Options:
      --bundle <BUNDLE>  Knowledge Bundle root directory (holds the Concept `.md` files)
      --json             Machine-readable JSON output
  -h, --help             Print help
```

The lint scans one bundle: `--bundle` when given, else the project's
resolved `<knowledge>` directory (same resolution as `varde-workflow
paths`).

## Checks

Five check kinds run on every invocation:

- **OrphanedConcept** — a Concept with zero incoming links from any other
  Concept in the bundle. Reserved bundle files (`index.md`, `log.md`,
  `README.md`) are not Concepts and are not counted as link sources.
- **BrokenLink** — a bundle-internal markdown link (an
  absolute bundle-relative `/…` or relative form) whose resolved target
  file does not exist in the bundle. External `http://`/`https://` links,
  images (`![alt](…)`), and `](` markers inside inline code spans or fenced
  code blocks are never treated as links. Anchor fragments
  (`b.md#section`) and angle-bracket targets (`<b.md>`) are stripped before
  resolving; a target that resolves to a directory is broken. Whether an
  existing target is itself a valid Concept is not checked here — that is
  `concept list`/`concept show`'s job.
- **MissingIndex** — a directory (the bundle root or any subdirectory)
  containing at least one Concept file but no `index.md` directly inside
  it.
- **MalformedConcept** — a `.md` file with YAML frontmatter that is not a
  valid Concept (unparseable frontmatter or missing the required `type`
  field). It is reported as its own issue and skipped by the other checks.
  Files without any frontmatter are not Concepts and are not linted.
- **UnreadableEntry** — a subdirectory or file the scan could not read
  (permissions, I/O error). It is reported and skipped; the scan keeps
  walking the rest of the bundle.

## Traversal scope

The walk skips hidden entries (`.git`, dotfiles), common artifact trees
(`target`, `node_modules`), and never follows symlinks (cycle guard).
`README.md` is bundle bookkeeping like `index.md`/`log.md` and is never a
Concept (note: `concept list` keeps the narrower `index.md`/`log.md` reserved set).

## Severities

- `Warning` — `MissingIndex` only: a missing `index.md` never fails a run.
- `Error` — `OrphanedConcept`, `BrokenLink`, `MalformedConcept`,
  `UnreadableEntry`.

## Exit codes and output

- Text output: one line per issue, `Error` before `Warning`, then by path,
  then by check kind — the same order `--json` emits.
- `--json`: the full issue list as a JSON array in the same order; each
  element carries `severity`, `check_kind`, `path`, and `message`.
- Exit `0` when the report is empty or contains only `Warning`-severity
  issues.
- Exit non-zero when any `Error`-severity issue exists.
- A genuine infrastructure failure (e.g. a `--bundle` path that does not
  exist) is a command error: printed to stderr, exits non-zero.

## Non-goals (this MVP)

- No auto-fix or auto-repair of any reported issue — report-only.
- No multi-bundle merging — the lint scans exactly one bundle.
- No semantic-contradiction detection or duplicate-alias checks.

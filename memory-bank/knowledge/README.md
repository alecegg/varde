# memory-bank/knowledge/

This directory is the project's durable Knowledge Bundle: markdown concept
files with YAML frontmatter. Commit concepts and review them like source
files. Keep personal knowledge outside this repository.

## Layout

Each concept is a Markdown file with YAML frontmatter. Its bundle-relative
path without `.md` is its Concept ID. For example, `decision/use-rust.md`
has ID `decision/use-rust`. Path segments use kebab case.

`index.md`, `log.md`, and `README.md` are reserved bundle files, never
concepts. Search and lint skip them. `concept map` can regenerate root and
type-directory indexes without changing concepts.

## Frontmatter

New concepts need a nonempty `type` and `description`. Common types here are
`decision`, `definition`, `pattern`, and `reference`. `title`, `tags`, and
`aliases` help discovery. `status` is a free-form string (absence implies
`stable`); it is never validated against a fixed set of values. Extension
fields are allowed. Structured fields (`sources`, `verified`, `generated`,
`stale_after`, `runtime`, `executor`, `attester`) must keep their required
list or object shapes — they can't be overwritten with a bare scalar.

```markdown
---
type: decision
title: Use Rust
description: Why the workflow CLI uses Rust.
tags:
  - implementation
status: stable
---

The decision and its reasons go here.
```

## CLI operations

Use `varde-workflow concept show` to get a concept's current version.
Pass that version through `--expected-version` when updating it.

```sh
varde-workflow concept list --bundle memory-bank/knowledge --json
varde-workflow concept search --bundle memory-bank/knowledge --text rust --json
varde-workflow concept map --bundle memory-bank/knowledge --json
varde-workflow lint --bundle memory-bank/knowledge --json
```

The default lint checks structural validity, orphaned concepts, broken
links, and duplicate aliases. `--require-index` additionally flags
directories with concepts but no `index.md`. Both commands report findings
without modifying concepts. See the [workflow CLI README](../../clis/workflow/README.md) for
complete command syntax.

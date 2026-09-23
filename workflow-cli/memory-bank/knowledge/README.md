# memory-bank/knowledge/

This directory is the project's durable Knowledge Bundle. It follows OKF v0.2.
Commit concepts and review them like source files. Keep personal knowledge
outside this repository.

## Layout

Each concept is a Markdown file with YAML frontmatter. Its bundle-relative
path without `.md` is its Concept ID. For example, `decision/use-rust.md`
has ID `decision/use-rust`. Path segments use kebab case.

`index.md` and `log.md` are reserved bundle files. This `README.md` is
repository guidance, not a concept. Search and lint skip it.
The root `index.md` declares `okf_version: 0.2`. `concept map` can regenerate
root and type-directory indexes without changing concepts.

## Frontmatter

New concepts need a nonempty `type` and `description`. Common types here are
`decision`, `definition`, `pattern`, and `reference`. `title`, `tags`, and
`aliases` help discovery. Optional `status` accepts `draft`, `stable`, or
`deprecated`. Extension fields are allowed. Structured OKF fields must keep
their required list or object shapes.

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
varde-workflow lint --bundle memory-bank/knowledge --okf --json
```

The default lint checks structural issues. `--okf` adds format checks.
Both commands report findings without modifying concepts. See the
[module README](../../README.md) for complete command syntax.

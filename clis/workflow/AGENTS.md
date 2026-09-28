# AGENTS.md

Instructions for AI agents working in the `workflow` module of the varde
monorepo. Read this file first (see the repo-root `AGENTS.md` for cross-module
conventions).

## What this module is

A markdown knowledge bundle CLI: Concept CRUD over a directory of markdown
files with YAML frontmatter, structural lint, and workflow artifact
validation and transitions.

CLI-only. No MCP server surface.

## Status

Pre-alpha. See `../../memory-bank/knowledge/decision/` for confirmed decisions
and `../../memory-bank/knowledge/definition/` for the project glossary.

## MVP scope (confirmed, see decision + readiness verdict)

1. Base-structural Concept/Knowledge Bundle CRUD by default (parseable
   frontmatter, UTF-8, kebab-case slug, no path traversal), with
   optimistic-concurrency-controlled writes (compare-and-swap; reject
   the losing write with a typed conflict error, never silent overwrite).
   `bundle_lint` runs its checks unconditionally except `MissingIndex`,
   which is opt-in via `lint --require-index`; lint never blocks
   create/update.
2. `bundle_lint` — structural health check: broken links and malformed
   frontmatter are errors; orphaned concepts and (opt-in) missing indexes
   are warnings.

## Language and tooling

Rust (see `../../memory-bank/knowledge/decision/implementation-language-rust.md`).

## Core vocabulary

See `../../memory-bank/knowledge/definition/` for full definitions. Key terms:

- **Concept** — a single unit of knowledge (one markdown file with YAML
  frontmatter).
- **Knowledge Bundle** — a self-contained, hierarchical collection of
  Concepts; the unit of distribution.
- **bundle_lint** — the structural health check.

## Coding standards

See `../../memory-bank/knowledge/pattern/conventions.md` for the full list.
Highlights:

- snake_case module filenames, file-per-module (no `mod.rs`).
- `thiserror` for typed errors in library/core crates; `anyhow::Result`
  only at the CLI command-handler boundary.
- Inline `#[cfg(test)] mod tests` for unit tests; top-level `tests/` for
  CLI integration tests exercising the built binary.
- OCC writes use compare-and-swap on a version field; every write path
  must leave the bundle in a consistent state on failure.

## Agent memory boundaries

- `../../memory-bank/knowledge/definition/` — glossary only. No implementation
  details, no rationale.
- `../../memory-bank/knowledge/decision/` — accepted decisions with What/Why/
  Constraints.
- `../../memory-bank/knowledge/pattern/` — concrete, testable style rules only.
- The configured working store (`varde-workflow paths --json`) holds transient plans, tasks, and reviews.

Do not duplicate content across these stores.

## Next step

Run `/varde-plan` to scope the first build increment (MVP item 1 above).

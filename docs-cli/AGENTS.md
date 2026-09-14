# AGENTS.md

Instructions for AI agents working in the `docs-cli` module of the varde
monorepo. Read this file first (see the repo-root `AGENTS.md` for cross-module
conventions).

## What this module is

An OKF (Open Knowledge Format) knowledge CLI. Implements the real OKF v0.2 spec
(https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
strictly, with design ideas from
[pi-llm-wiki](https://github.com/zosmaai/pi-llm-wiki) for personal/project
knowledge layering and contradiction-aware linting.

CLI-only. No MCP server surface.

## Status

Pre-alpha. See `memory-bank/knowledge/decision/` for confirmed decisions
and `memory-bank/knowledge/definition/` for the project glossary.

## MVP scope (confirmed, see decision + readiness verdict)

1. Base-structural Concept/Knowledge Bundle CRUD by default (parseable
   frontmatter, UTF-8, kebab-case slug, no path traversal), with
   optimistic-concurrency-controlled writes (compare-and-swap; reject
   the losing write with a typed conflict error, never silent overwrite).
   Full OKF v0.2 spec conformance is opt-in via `lint --okf`, and never
   blocks create/update.
2. Personal Vault + Project Vault layering, merged at recall time.
   Project Vault wins on same-slug collisions.
3. `bundle_lint` — contradiction-aware health check (orphans, broken
   links, duplicate aliases, coverage gaps, semantic contradictions).

Explicitly deferred: the four-layer raw-source/source-page/canonical-page/
meta pipeline split from pi-llm-wiki.

## Language and tooling

Rust (see `memory-bank/knowledge/decision/implementation-language-rust.md`).

## Core vocabulary

See `memory-bank/knowledge/definition/` for full definitions. Key terms:

- **Concept** — a single unit of knowledge (one markdown file with YAML
  frontmatter), per OKF v0.2 §2.
- **Knowledge Bundle** — a self-contained, hierarchical collection of
  Concepts; the unit of distribution.
- **Personal Vault** — a Knowledge Bundle scoped to the user across all
  projects.
- **Project Vault** — a Knowledge Bundle scoped to a single project/repo.
- **bundle_lint** — the contradiction-aware health check.

## Coding standards

See `memory-bank/knowledge/pattern/conventions.md` for the full list.
Highlights:

- snake_case module filenames, file-per-module (no `mod.rs`).
- `thiserror` for typed errors in library/core crates; `anyhow::Result`
  only at the CLI command-handler boundary.
- Inline `#[cfg(test)] mod tests` for unit tests; top-level `tests/` for
  CLI integration tests exercising the built binary.
- OCC writes use compare-and-swap on a version field; every write path
  must leave the bundle in a consistent state on failure.

## Agent memory boundaries

- `memory-bank/knowledge/definition/` — glossary only. No implementation
  details, no rationale.
- `memory-bank/knowledge/decision/` — accepted decisions with What/Why/
  Constraints.
- `memory-bank/knowledge/pattern/` — concrete, testable style rules only.
- `memory-bank/working/` — transient plans/tasks/reviews. High churn.

Do not duplicate content across these stores.

## Next step

Run `/varde-plan` to scope the first build increment (MVP item 1 above).

# AGENTS.md — varde monorepo

This repo combines three previously separate projects into one working tree. It is a **monorepo with convention-based module boundaries**, not a unified build.

## Module convention

Each top-level folder is a self-contained module:

- `skills/` — the `varde-*` skills (markdown + shell tooling).
- `agents/` — installable subagent definitions, one variant per harness (markdown + shell tooling).
- `code-cli/` — the `varde-code` Rust CLI (its own Cargo workspace).
- `docs-cli/` — the `varde-docs` / `okf-core` / `docwatch` Rust CLIs (its own Cargo workspace).

Rules that keep the modules independent:

1. **No cross-folder source or dependency imports.** `code-cli/` and `docs-cli/` are separate Cargo workspaces and must stay that way — do not add a root `Cargo.toml`, and do not add path dependencies from one folder into another. The skills reach the CLIs only through the installed binaries on `PATH`, never by relative path into a sibling folder.
2. **Build and test within a folder.** `cd code-cli && cargo test`, `cd docs-cli && cargo test`, `cd skills && ./install.sh`, `cd agents && ./install.sh`. There is no root build or test entry point.
3. **Names keep the `varde-` prefix.** Folders are short (`code-cli/`, `docs-cli/`, `skills/`, `agents/`), but package names, CLI names, and skill names retain their full `varde-*` identity (`varde-code`, `varde-docs`, `varde-plan`, …).
4. **Each folder owns its own docs.** Per-folder `README.md`, `AGENTS.md`/`CLAUDE.md`, and `memory-bank/` govern work inside that folder. When working in a folder, follow its local instructions.

## Provenance

These folders were imported fresh (no combined git history). The original per-project history remains in the standalone repositories they came from.

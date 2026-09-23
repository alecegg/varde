# Patterns

## File Naming Conventions

- Use snake_case for all Rust module filenames.
- Use file-per-module (2018+ style, no `mod.rs`) for module layout.
- One CRUD operation per file under `okf-core/src/crud/<operation>.rs`.
- Cross-cutting logic (shared validation, errors) lives in a parent-level file (`crud.rs`, `commands/error.rs`), not duplicated per operation.

## Code Structure

- Use `thiserror` for typed errors in library/core crates.
- Use `anyhow::Result` at the CLI/MCP command-handler boundary only.

## Test Patterns

- Write unit tests inline in a `#[cfg(test)] mod tests` block at the bottom of each file.
- Write CLI integration tests exercising the built binary in a top-level `tests/` directory.

## Data Integrity

- Use optimistic concurrency control (version field compare-and-swap) for concurrent writes to a Concept file.
- Reject a losing concurrent write with a typed conflict error; never silently overwrite.

## Correctness

- Validate every input Concept against base structural rules only (frontmatter is a parseable YAML mapping, valid UTF-8, kebab-case slug, no path traversal) at the point it enters the bundle, before it is persisted. `type`/`status`/OKF-spec conformance is opt-in, checked only via `lint --okf`, never blocking on create/update — see `okf-core/src/lint/base.rs` (`lint_base`) vs `okf-core/src/lint.rs` (`lint` vs `lint_okf`).
- Every OCC write path must leave the bundle in a consistent state on failure — a rejected or errored write must not partially modify the file.

## Gotchas

- `varde-worktree` skill scripts (`create.sh`/`merge.sh`/`cleanup.sh`) resolve `repo_root`/`worktree_path` from the invoking shell's cwd via `git rev-parse --show-toplevel`, not from an explicit repoRoot argument — always `cd` into the intended worktree (e.g. the plan's staging worktree) before invoking them, or they'll silently operate against whatever checkout happens to be current (this once merged a task branch directly into `main` instead of the staging branch).
- Changing core CRUD validation behavior (e.g. removing the missing-`type` rejection) can leave stale CLI-level integration tests in `varde-workflow/tests/*.rs` asserting the old behavior even when no task's `modifies` list names them — when planning a behavior change to `okf-core`, check `varde-workflow/tests/` for tests asserting the old behavior, not just `okf-core`'s own unit tests.

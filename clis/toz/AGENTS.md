# AGENTS.md — toz

Toz (tool-output-zone) keeps large tool output out of a coding agent's context window.

## Workspace

- The `varde-toz` package is part of the workspace rooted at `clis/Cargo.toml`.
- From `clis`, test it with `cargo test -p varde-toz --locked`.
- Install the unified CLI with `cargo install --path varde --locked --force --target-dir target` from `clis`.
- Follow the repository-root `AGENTS.md` for shared-crate rules and module boundaries.

On macOS, the two Seatbelt sandbox tests in
`clis/varde/tests/toz/cli.rs` (`cd clis && cargo test -p varde --test toz_cli
--locked sandbox`) fail with `sandbox_apply: Operation not permitted` when run
inside an outer sandbox; rerun just those with the sandbox disabled.

Format with `rustfmt --edition 2021 <file>` on owned files only, never
`cargo fmt`. rustfmt also formats out-of-line `mod` children, so check every
touched path afterward.

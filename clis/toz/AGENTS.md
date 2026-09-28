# AGENTS.md — toz

Toz (tool-output-zone) keeps large tool output out of a coding agent's context window.

Build and test within this folder: `cd clis/toz && cargo test --workspace`. On
macOS, the two Seatbelt sandbox tests in `crates/toz/tests/cli.rs`
(`cargo test -p varde-toz --test cli sandbox`) fail with `sandbox_apply:
Operation not permitted` when run inside an outer sandbox; rerun just those
with the sandbox disabled.

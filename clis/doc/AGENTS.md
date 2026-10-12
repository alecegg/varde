# AGENTS.md — doc

This module provides the `varde-doc` package in the Rust workspace rooted at
`clis/Cargo.toml`. Its commands are exposed through the unified `varde` CLI. The
user-facing reference is [README.md](./README.md).

## Workspace

- Build and test from the workspace root: `cd clis && cargo test -p varde-doc --locked`.
- Install the unified CLI: `cd clis && cargo install --path varde --locked --force --target-dir target`.
- Format with `rustfmt --edition 2024 <file>` on owned files only, never
  `cargo fmt`.
- Follow the repository-root `AGENTS.md` for shared-crate and dependency rules;
  module crates depend only on `varde-core` and `varde-contracts`.
- The lint rules live in `varde_core::text_audit`; this crate only expands
  paths, renders text, and builds envelopes.
- `varde doc flow` lives in `crates/varde-doc/src/flow/`: `scan.rs` and
  `analyze.rs` build the analysis, `render.rs` prints text, Mermaid and
  `FLOW.md`; the command wiring is in `src/lib.rs`.
- `varde doc frontmatter` lives in `crates/varde-doc/src/frontmatter.rs`. It
  parses with `serde_yaml` (YAML 1.2), which drops `!!` tags, so a raw scan
  rejects them (only where YAML allows a tag). A quoted `"<<"` key is not a
  merge; a raw scan decides. `serde_yaml`'s own `apply_merge` skips nested merges, so the
  module resolves `<<` itself. Read the divergence notes at the top of that
  file before changing the validation.

## Tests

`crates/varde-doc/tests/parity.rs` compares the text output over a frozen
corpus (`tests/fixtures/corpus/`, Markdown copied from base commit `b768588d`)
with `tests/fixtures/corpus-expected.txt`. Skill edits do not affect it.
Regenerate the expectation only if the corpus changes: run the base script
(`git show b768588d:skills/varde-agent-doc-authoring/scripts/check-length.py`)
from `tests/fixtures` over the `corpus/` paths listed in `parity.rs`, in that
order. The test strips the fixtures directory prefix so paths print as
`corpus/...`.
`crates/varde-doc/tests/frontmatter.rs` ports the old Python validator tests with
temp directories. Binary-spawning tests live in `clis/varde/tests/doc_lint.rs`
and `clis/varde/tests/doc_frontmatter.rs`.

`crates/varde-doc/tests/flow_parity.rs` compares `varde doc flow` text,
`--mermaid`, `--json` (by value) and `FLOW.md` output with the base script over
a frozen corpus, `tests/fixtures/flow/corpus.txt`: sections headed
`=== <relative path> ===` holding `varde-change` and `varde-docs` from base
commit `b768588d` (only the files the analysis reads), the `skills/shared`
files listed for them, the `agents/*/claude.md` definitions, and a synthetic
`varde-flow-gaps` skill for the missing, unreferenced and cycle findings.
Skill edits do not affect it. Regenerate the `expected-*` files only if the
corpus changes; the test header lists the commands (unpack the corpus, run the
base script `git show b768588d:skills/varde-agent-doc-authoring/scripts/skill-flow.py`
over `varde-change varde-docs varde-flow-gaps`, and change the FLOW.md header
line as documented there). Binary tests for the flow command live in
`clis/varde/tests/doc_flow.rs`.

---
type: pattern
title: varde-code coding patterns
---

# Patterns

## File Naming Conventions

- Use one snake_case file per language/subsystem unit, named after what it handles (e.g. `extract/langs/go.rs`, `extract/langs/java.rs`).

## Code Structure

- Order each extractor module as: `//!` module doc explaining node-kind mappings, then `pub const` scope/kind tables, then a `pub fn visit` dispatcher matching on `node.kind()`.
- Implement each query mode as its own function, dispatched from a thin match/switch — not folded into one large function handling all modes.

## Test Patterns

- Put integration tests in the crate's top-level `tests/` dir, one file per concern (e.g. `tests/extract_symbols.rs`, `tests/coverage_parity.rs`).
- Drive tests from fixture files under `tests/fixtures/<lang>/` rather than inline source strings.

## Quality Principles

### Correctness

- A query mode with no matches returns an empty result, not an error; an unknown/missing symbol or file name returns an explicit not-found error.
- Graph-traversal modes (dependencies, blast_radius, type_hierarchy) must terminate on cyclic input rather than looping infinitely.

### API Design

- Every query mode's CLI JSON output shares one consistent top-level envelope shape (success/error discriminant + typed payload) rather than a per-mode ad-hoc shape.

### Readability

- Document every public query-mode function with a doc comment stating its inputs, outputs, and error conditions.

### Performance

- Avoid N+1 SQLite query patterns in query-mode implementations — batch or join instead of issuing one query per row in a loop.

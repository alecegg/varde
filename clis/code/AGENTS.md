# Agent notes for varde-code

## Workspace

This is the `varde-code` package in the Rust workspace rooted at
`clis/Cargo.toml`. From `clis`, test it with `cargo test -p varde-code --locked`;
install the unified CLI with `cargo install --path varde --locked --force --target-dir target`.
Follow the repository-root `AGENTS.md` for shared-crate rules, including the
boundary between module crates.

## Performance constraint: parity with ast-grep

Any query mode that overlaps functionality already provided by `ast-grep` (the
upstream CLI/crate this project depends on for grammar loading and, for
`find_pattern`, pattern-matching semantics) must run in **no more than 2x** the
wall-clock time of the equivalent `ast-grep` invocation on the same input.

- Benchmark on the same target (same repo/dir, same file set) and the same
  pattern/query, run warm (repeat 3x, take the stable number) — see
  `2026-09-03` session notes for the methodology used to first measure this
  (cold vs. warm cache separated; `ast-grep` installed via
  `cargo install ast-grep` for a same-version baseline against the
  `ast-grep-core`/`ast-grep-language` versions the code module depends on).
- If a change regresses a query past the 2x threshold, that's a blocking
  finding, not a nice-to-have — fix it before merging, don't defer it.
- Fixed as of 2026-09-03: `find_pattern` now matches `ast-grep run`'s speed and
  results. The fix parallelized file walks and corrected a trailing-comma
  match bug; see `BENCHMARK.md` for measurements and implementation details.
- Fixed as of 2026-09-03: `varde map build`'s churn perf bug. It was
  spawning one `git log -- <file>` subprocess per file (2m19s to index ~40
  files against `~/source/varde`). Replaced with `churn::commit_counts_batch`
  — one `git log --name-only` walk per git repo root, counts kept in memory.
  Same ~40-file target now takes ~1.9s wall (~74x faster). `build` was then
  benchmarked cold/end-to-end against `ast-grep outline` — fails the 2x
  budget (~10-40x slower) but judged not a blocking regression due to a
  genuine scope mismatch (full indexing pipeline vs. single-shot parse); see
  `BENCHMARK.md` for the full reasoning.

## Agent guidance

Each consuming skill owns a `references/varde-code.md` for its CLI use. When a
command changes, update each skill that documents it; there is no shared copy.

Repository-only benchmarking guidance remains under `.claude/skills/`.

Format with `rustfmt --edition 2024 <file>` on owned files only, never
`cargo fmt`. rustfmt also formats out-of-line `mod` children, so check every
touched path afterward.

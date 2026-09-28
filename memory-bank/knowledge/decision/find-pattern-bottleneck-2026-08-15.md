---
status: accepted
title: find_pattern warm-run bottleneck profile (post-rayon) and matcher-fix verdicts
type: decision
paths: ["crates/varde-code/src/query/find_pattern.rs"]
enriched_at_commit: null
generated:
  by: agent:claude
  at: 2026-08-15T00:00:00.000Z
verified:
  - by: agent:claude
    at: 2026-08-15T00:00:00.000Z
---

## What

Profiled a warm `find_pattern` run (TS `console.log($MSG)` on
`~/source/reference-repos/oh-my-pi`, matching `BENCHMARK.md`'s existing row)
against the release binary using macOS `sample` (1ms interval, 4s window,
built with `CARGO_PROFILE_RELEASE_DEBUG=true CARGO_PROFILE_RELEASE_STRIP=false`
for symbols; `cargo-flamegraph`/`samply`/`perf` were unavailable in this
sandbox — no network access to crates.io and `perf` isn't installed on
macOS). Ran with `RAYON_NUM_THREADS=1` so all worker-thread samples land on
one attributable call stack (main thread just blocks in
`_pthread_cond_wait`/`__psynch_cvwait`, discarded from the analysis below).

Leaf-frame ("top of stack") sample counts, ~2576 non-idle samples,
classified by source-level responsibility:

| Category | Leaf samples | Share | Key symbols |
|---|---|---|---|
| tree-sitter parse (`ts_parser_parse` + lexer/subtree/stack machinery) | 1060 | ~41% | `ts_parser_parse` 332, `ts_lexer__do_advance` 116, `ts_lex` 115, `ts_subtree_summarize_children` 92, `ts_stack_push` 73, `ts_subtree_release` 61, `ts_parser__reduce` 43, … |
| tree-cursor child iteration (`node.children()` walks) | 945 | ~37% | `ts_tree_cursor_child_iterator_next` 470, `ts_tree_cursor_goto_sibling_internal` 137, `ts_tree_cursor_goto_first_child_internal` 134, `ts_tree_cursor_current_node` 68, `ts_node_type` 48, `ts_tree_cursor_new` 31, `ts_node_child_count` 23 |
| malloc/free (mostly `Vec`/`Value` allocation churn) | 340 | ~13% | `_xzm_free` 131, `_xzm_xzone_malloc_tiny` 79, `_malloc_zone_malloc` 33, `_free` 32, `_xzm_xzone_malloc` 21 |
| UTF-8/str conversion | 159 | ~6% | `core::str::from_utf8` 100, `_platform_strlen` 29, `_platform_memset` 13, `_platform_memmove` 12 |
| our matcher code (self time, not children) | ~50 | ~2% | `find_matches` 22, `meta_of` 14, `open` (file read) 27 |

Source-level attribution: `pattern.children().collect()` /
`source.children().collect()` appear at `find_pattern.rs:230,235` inside
`match_node` and again at `find_pattern.rs:631,632` inside
`collect_captures`; `find_matches` (`find_pattern.rs:289`) does its own
uncollected `for child in node.children()` walk. All four call sites go
through the same `ts_tree_cursor_child_iterator_next`-backed iterator, so
the ~37% "tree-cursor" bucket is the combined cost of the structural
recursive-descent search (`find_matches`) *plus* the repeated
subtree-children collection that `match_node` performs on every candidate
node it tests (most of which fail to match) *plus* `collect_captures`'s
re-walk on confirmed matches. `tick_budget`/`reset_budget`
(`find_pattern.rs:97,109`) produce no visible leaf samples at all — the
thread-local `Cell` increments are cheap enough to be inlined/folded away
by LLVM at `-O3`/LTO.

## Top cost centers (by measured share)

1. **Tree-sitter parsing** (~41%) — largely fixed cost of turning source
   text into a CST; none of the four candidate fixes target this.
2. **Tree-cursor-based child iteration / `Vec` collection during matching**
   (~37%) — this is what Fix 1 and Fix 2 both touch, from different
   angles: Fix 1 removes the per-node `.collect::<Vec<_>>()` in
   `match_node`; Fix 2 removes the redundant re-walk in
   `collect_captures`/`bind_sequence` after `find_matches` already located
   the match.
3. **Allocation churn** (~13%) — shared pool covering the `Vec<PNode>`
   collections from (2) and `serde_json::Value` tree construction (Fix 3's
   target) together; not separable from sample data alone, but bounded
   above by 13% of total CPU, and Fix 3 only runs per *confirmed match*
   (a small fraction of total nodes visited) vs. Fix 1/2's per-node-visited
   cost, so Fix 3's share of this 13% is necessarily the smaller of the
   two.
4. **UTF-8 conversion** (~6%) — not targeted by any of the four fixes.

## Per-fix verdicts

- **Fix 1 (child-traversal allocation in `match_node`, `.collect::<Vec<_>>()`
  per node visited) — CONFIRM.** `match_node` is invoked once per node
  `find_matches` visits as a *candidate* (line 289), and on most real files
  most candidates fail to match — meaning `match_node`'s two
  `.collect::<Vec<_>>()` calls (pattern children + source children,
  lines 230/235) execute on the hot path for the large majority of nodes in
  the tree, not just for eventual matches. This lines up with
  `ts_tree_cursor_child_iterator_next` being the single largest individual
  leaf symbol (470/2576, ~18% alone). Eliminating the eager collect (e.g.
  iterating cursors directly, or short-circuiting on child-count/kind
  mismatch before collecting) is a real, well-targeted fix.

- **Fix 2 (double structural walk per match: `find_matches` locates, then
  `collect_captures`/`bind_sequence` re-walks to bind) — CONFIRM, but
  smaller magnitude than Fix 1.** The re-walk in `collect_captures`
  (`find_pattern.rs:631,632`) only runs once per *confirmed* match, which
  on this corpus is a small fraction of total nodes visited (`find_matches`
  visits every node in every file; only actual `console.log(...)` sites
  trigger `collect_captures`). It's a real, avoidable structural walk, but
  it isn't where the bulk of the ~37% cursor-iteration time is going —
  most of that time is `match_node`'s failed-candidate testing (Fix 1's
  territory), not the confirmed-match binding walk.

- **Fix 3 (per-match `serde_json::Value` tree construction, `node_json`,
  `json!` macros) — REFUTE as a significant contributor.** This only runs
  per confirmed match (same small subset as Fix 2), and its cost is folded
  into the ~13% malloc/free bucket alongside the much-more-frequent
  `Vec<PNode>` allocations from Fix 1/2's territory. Given match count
  << node-visit count on this corpus, `node_json`/`json!` construction is
  a minority contributor within that already-modest 13% slice — not worth
  prioritizing ahead of Fix 1.

- **Fix 4 (backtracking-budget bookkeeping, `tick_budget`/`reset_budget`
  thread-local `Cell` access) — REFUTE.** No leaf samples attributable to
  these functions appear anywhere in the profile (cutoff was symbols with
  ≥5 samples out of ~2576); the `Cell::get`/`set` pair is cheap and almost
  certainly inlined away under LTO + `codegen-units=1`. No evidence this
  is a real cost center.

## Does the 2026-08-13 finding still hold?

**Partially — the finding was correct about *wall-clock* under the old
sequential walk, but the reason has changed, and it no longer predicts
what happens post-parallelization.**

Commit `b9da284`'s finding was that a kind pre-filter in `find_matches` and
an allocation short-circuit in `strip_trailing_commas`/`strip_trivia` did
not move the wall-clock at all, under a *sequential* per-file directory
walk. This profile shows tree-sitter parsing alone accounts for ~41% of
per-file CPU time — larger than the entire tree-cursor/allocation bucket
those 08-13 changes targeted. Under a sequential walk, wall-clock is the
sum of every file's CPU time; if the 08-13 changes shaved only a slice of
the ~37% matcher-walk bucket (and neither change was `match_node`'s
`.collect::<Vec<_>>()`, which this profile shows is the largest individual
symbol), the improvement would likely have been below the noise floor
against the dominant ~41% parse cost plus I/O — consistent with the
observed null result.

Post-`rayon`-parallelization, the picture for *this task's specific
question* — is Fix 1/2's target (the ~37% cursor-walk bucket) large enough
to matter — has **not** fundamentally changed: parallelizing the directory
walk divides *both* the parse cost and the matcher-walk cost by the same
factor (files run on separate rayon workers, each doing its own
parse+match+capture), so it does not change the *relative* share of parse
vs. matcher-walk vs. allocation within a single file's critical path — it
only reduces wall-clock proportionally to core count for the whole
workload. What *does* change the calculus is that Fix 1 targets a bucket
(~37%, dominated by `match_node`'s eager collect) that is comparable in
size to the parse cost (~41%) — large enough that, unlike the specific
08-13 changes (kind pre-filter + `strip_trivia` short-circuit, which did
not touch `match_node`'s collect), a fix that actually removes the
per-candidate-node `Vec` allocation should be measurable in wall-clock,
parallelized or not. In short: the *specific* 08-13 experiment's null
result still stands (those two changes really didn't touch the biggest
cost center), but it should not be read as "matcher-internal tuning in
general doesn't matter" — Fix 1, which wasn't part of that experiment,
targets a genuinely large slice of per-file CPU time.

## Constraints / caveats

- Single profiling run (`sample`, 4s window, ~2576 non-idle leaf samples)
  on one repo/pattern; no cross-repo or cross-pattern validation was in
  scope per this task's "out of scope" section.
- `sample`'s leaf-frame classification can't perfectly separate Fix 1's
  vs. Fix 2's vs. Fix 3's share within the shared malloc/free pool — the
  verdicts above are argued from call-site frequency (candidate nodes
  visited vs. confirmed matches), not a fully attributed allocation
  profile. A follow-up with an allocation-sampling tool (e.g. `heaptrack`
  equivalent, or `DYLD_INSERT_LIBRARIES` malloc stack logging) could
  sharpen the Fix 1/2/3 split further if the implementation task needs it.
- This task intentionally did not implement any of the four fixes; the
  verdicts above are inputs to prioritization, not measured before/after
  deltas.

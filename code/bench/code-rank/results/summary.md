# Code retrieval ranking benchmark

# Result

Lexical fusion did not beat structural ranking on this benchmark. The shipped
default is `fallback`: it has the same measured NDCG@10 as structural and
recovered 0/48 structural zero-hit queries. Fallback remains because lexical
retrieval can rescue sparse structural queries that would otherwise return
`not_found`; the benchmark has no `not_found` results, so it does not measure
that benefit. The held-out OpenSpec and agent-deck repositories score NDCG@10
0.0 for every ranker and cannot distinguish them. The not-found rescue is
supported by the focused unit and fixture test, not this benchmark.

## Historical fused benchmark (pre-tuning)

Historical invocation: `--ranker both` compared structural and fused at the
time; the current benchmark CLI compares structural and fallback with `both`.

The content-based query set contains 100 queries: 55 commit-derived and 45
handwritten. One full combined run completed (100 queries per ranker) with exit
code 0. A prior invocation stopped at an agent-deck index lock timeout before
retrieval and is excluded. The completed run reported zero errors and zero
not-found results for both rankers. Token coverage compares expected tokens to
the first relevant result against grep-then-read; higher is better. Misses are
capped at 32,000 tokens.

## Aggregate

| Ranker | NDCG@10 | Token coverage | Expected tokens | Grep-then-read tokens | Relevant hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Structural | 0.1152 | 3.4248x | 63,237.0 | 216,572.2 | 52/100 |
| Fused | 0.0637 | 3.4134x | 61,743.9 | 210,755.0 | 44/100 |

## Per repository

| Repository | Queries | Structural NDCG@10 | Structural token coverage | Structural hits | Fused NDCG@10 | Fused token coverage | Fused hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| varde | 70 | 0.1645 | 5.6702x | 45/70 | 0.0910 | 4.8975x | 35/70 |
| OpenSpec | 15 | 0.0000 | 0.7284x | 6/15 | 0.0000 | 0.7393x | 8/15 |
| agent-deck | 15 | 0.0000 | 1.9054x | 1/15 | 0.0000 | 3.4656x | 1/15 |

## Per query source

| Source | Queries | Structural NDCG@10 | Structural token coverage | Structural hits | Fused NDCG@10 | Fused token coverage | Fused hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Commit | 55 | 0.2094 | 6.6582x | 44/55 | 0.1158 | 5.5586x | 34/55 |
| Handwritten | 45 | 0.0000 | 1.2771x | 8/45 | 0.0000 | 1.4821x | 10/45 |

## Index timing

Previously measured index timings, averaged over 3 runs:

| Operation | Before | After |
| --- | ---: | ---: |
| Full build | 114.8s | 124.9s |
| 1-file refresh | 4.59s | 4.25s |
| Unchanged index | 0.061s | 0.050s |

In this historical run, fused did not improve NDCG@10 over structural.
Aggregate token coverage was effectively unchanged (3.4248x structural,
3.4134x fused). The values are retained as a dated record of the pre-tuning
experiment; they describe fused, which is no longer a production ranking mode.

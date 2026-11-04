# Fusion tuning

All runs used the 100-query corpus (70 varde, 15 OpenSpec, 15 agent-deck),
one completed run per variant, with 0 errors and 0 not-found results. Token
coverage is grep-then-read tokens divided by retrieval tokens; it varies slightly
between runs because the benchmark baseline is measured again each time.
Each run copies the current worktree as the varde corpus, so only structural
versus variant pairs within the same run are comparable. Tables below are
historical experiment records; `fused` and `append` are not production modes.

The historical baseline run recorded before tuning is also in `summary.md`
(fused varde NDCG@10 0.0910, structural 0.1645). A fresh diagnostic baseline
run gave the following per-repository metrics:

| Repository | Structural NDCG@10 | Structural token coverage | Fused NDCG@10 | Fused token coverage |
| --- | ---: | ---: | ---: | ---: |
| varde | 0.1645 | 6.2394x | 0.0900 | 5.0176x |
| OpenSpec | 0.0000 | 0.7275x | 0.0000 | 0.7006x |
| agent-deck | 0.0000 | 1.9006x | 0.0000 | 3.4111x |

## Variant: lexical top 30

Only the first 30 lexical entities contribute file scores to fusion; all lexical
matches remain available for symbol output.

| Repository | Structural NDCG@10 | Structural token coverage | Fused NDCG@10 | Fused token coverage |
| --- | ---: | ---: | ---: | ---: |
| varde | 0.1767 | 5.4591x | 0.1115 | 4.8819x |
| OpenSpec | 0.0000 | 0.6829x | 0.0000 | 0.7850x |
| agent-deck | 0.0000 | 1.6034x | 0.0000 | 1.9015x |

## Variant: lexical top 5

Only the first 5 lexical entities contribute file scores to fusion; all lexical
matches remain available for symbol output.

| Repository | Structural NDCG@10 | Structural token coverage | Fused NDCG@10 | Fused token coverage |
| --- | ---: | ---: | ---: | ---: |
| varde | 0.1767 | 5.7592x | 0.0938 | 4.6119x |
| OpenSpec | 0.0000 | 0.7277x | 0.0000 | 0.7699x |
| agent-deck | 0.0000 | 1.2490x | 0.0000 | 2.2095x |

## Variant 3: fallback

On the same 100-query corpus, the structural baseline and fallback results were:

| Repository | Structural NDCG@10 | Structural token coverage | Fallback NDCG@10 | Fallback token coverage |
| --- | ---: | ---: | ---: | ---: |
| varde | 0.1767 | 5.4982x | 0.1767 | 5.4336x |
| OpenSpec | 0.0000 | 0.7246x | 0.0000 | 0.7320x |
| agent-deck | 0.0000 | 1.3160x | 0.0000 | 1.2660x |

Structural ordering stays in effect for three or more seed files. With fewer
than three seeds, the capped RRF path is used. There were no retrieval errors
or not-found results in this run.

## Variant 4: append

On the same 100-query corpus, the structural baseline and append results were:

| Repository | Structural NDCG@10 | Structural token coverage | Append NDCG@10 | Append token coverage |
| --- | ---: | ---: | ---: | ---: |
| varde | 0.1767 | 5.4982x | 0.1767 | 5.9949x |
| OpenSpec | 0.0000 | 0.7246x | 0.0000 | 0.7285x |
| agent-deck | 0.0000 | 1.3160x | 0.0000 | 1.3709x |

Append keeps structural seeds in structural order, then places up to 10
lexical-only files before graph neighbors. There were no retrieval errors or
not-found results in this run.

## Structural zero-hit recovery

The recovery cohort is the 48 queries where structural returned `not_found` or
had no relevant path anywhere in its `files` output. Each cell is recovered
queries / cohort size; recovery means the ranker's `files` output contains at
least one relevant path.

| Repository | Cohort | Structural | Fused top 30 | Fallback | Append |
| --- | ---: | ---: | ---: | ---: | ---: |
| All | 48 | 0/48 | 2/48 | 0/48 | 0/48 |
| varde | 25 | 0/25 | 0/25 | 0/25 | 0/25 |
| OpenSpec | 9 | 0/9 | 2/9 | 0/9 | 0/9 |
| agent-deck | 14 | 0/14 | 0/14 | 0/14 | 0/14 |

## Diagnostic and finding

The baseline diagnostic shows the first relevant file at positions 29, 35, 75,
and 96 in several varde commit queries, or absent from `files` altogether.
Those positions are the actual output array positions (also the `files` portion
of `readingOrder`), so the loss is not only a mismatch between ranking scores
and output order. Fused lexical expansion adds competing seed files before
structural neighbors. Limiting the lexical contribution to 30 improves varde
fused NDCG@10 over the fresh baseline, but it remains below structural; top 5 is
worse than top 30. Fallback matches structural NDCG and preserves its ordering
for queries with at least three structural seeds. It is the selected default
because it keeps the structural result when the match is broad, while retaining
fusion for sparse matches. None of the variants recovered a varde structural
zero-hit query. No labels or queries were changed.

The structural ranking branch was not modified. Its output is exercised by
`code/tests/query/test_mapping_nav.py::test_context_pack_fuses_docstring_matches_and_keeps_structural_mode`.

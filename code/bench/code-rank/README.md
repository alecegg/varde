# Code retrieval rank benchmark

Run from the repository root:

```sh
uv run python code/bench/code-rank/run.py --ranker structural --limit 10
uv run python code/bench/code-rank/run.py --ranker fallback --limit 10
uv run pytest code/bench/code-rank -q
```

The benchmark calls `varde map context_pack` once per query. The checked-in
query set labels this Varde checkout and the OpenSpec and agent-deck reference
repositories. It combines commit-derived queries (commit subjects paired with
their changed files; merge commits, changes over eight files, and subjects that
repeat a touched path token are excluded) with hand-written behavior questions.
The reference checkouts have single-commit histories, so their labels are
hand-written. Tests ensure queries do not share tokens of three or more
characters with relevant paths.

NDCG@10 uses binary file relevance. Token coverage compares estimated tokens
read through the first relevant result with a grep-then-read baseline. That
baseline searches the three least frequent non-stopword query terms. Values
above 1x mean fewer tokens to the first hit for context_pack. Token counts use
a deterministic lexical approximation, not a model tokenizer. Each run prints
ranker errors and not-found results; any ranker error makes the command exit
nonzero.

---
topic: varde-improve/evals-compare
version: 1
summary: Eval step 4 of 6 - billed, needs the user's explicit cost approval - budget, compare runs
---

## Compare runs

- The runner compares with-skill and without-skill runs. Budget roughly
  `evals × configs × runs × 2` billed calls when every assertion is
  judge-graded. One run is a screen; use at least three per arm for a
  comparison.
- In `benchmark.json`, treat blocked runs and runs without assertions as
  inconclusive; they do not count toward pass rates or the minimum comparison
  runs. Report measured cost and tokens. Unavailable cost is unknown, not zero.
- When the run needs Git history, sandbox it in a disposable standalone clone,
  never a linked worktree.
- To compare skill versions, run identical eval files against each snapshot
  with `--no-baseline` and compare pass rates, token usage, and available cost
  in `benchmark.json`.

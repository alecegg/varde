# Evaluating skill output quality (agentskills.io)

Eval-driven iteration: does the skill produce reliably good output, across varied prompts and edge cases, better than no skill?

## Test cases: `evals/evals.json`

Each test case: a realistic **prompt**, a human-readable **expected_output**, optional **input files**. Start with 2-3 cases — don't over-invest before a first round of results. Vary phrasing/formality, include at least one edge case (malformed input, ambiguous request), use realistic context (real file paths, not "process this data").

```json
{
  "skill_name": "csv-analyzer",
  "evals": [
    {
      "id": 1,
      "prompt": "I have a CSV of monthly sales data in data/sales_2025.csv. Can you find the top 3 months by revenue and make a bar chart?",
      "expected_output": "A bar chart image showing the top 3 months by revenue, with labeled axes and values.",
      "files": ["evals/files/sales_2025.csv"]
    }
  ]
}
```

## Automated runner: `run-output-evals.sh`

`scripts/run-output-evals.sh <skill-dir>` automates the running → grading →
aggregating loop below: for every case in `<skill-dir>/evals/evals.json` it runs
the prompt WITH the skill (it prepends "read and follow `SKILL.md`") and, unless
`--no-baseline`, WITHOUT it, grades each assertion PASS/FAIL with an LLM judge
(`claude -p`, evidence required), and writes the `iteration-N/` tree plus
`benchmark.json` with the with/without delta. `--runs N` repeats each config so
stddev is meaningful; `--iteration N` labels the workspace subdir. It is the
output-quality counterpart to `run-evals.sh` (which measures *triggering*).

Two things it deliberately does *not* do, so know when to fall back to the manual
loop: (1) grading is LLM-judge only — for mechanically-checkable assertions (valid
JSON, exact error string, row counts) a verification script is more reliable, so
grade those by hand or extend the runner. (2) Each run executes in a throwaway
`mktemp` dir by default; a skill that needs real repo state (git history, existing
`memory-bank/` files) will misbehave there — point `--sandbox-dir` at a disposable
clone/worktree so the run has state to act on and the real tree is never mutated.
It spawns ~`evals × configs × runs × 2` billed `claude -p` calls; start with 2-3
evals at `--runs 1`.

## Running: with-skill vs. without-skill (or vs. previous version)

Each run needs a clean context — no leftover state (subagents give this naturally). Organize as:

```
csv-analyzer-workspace/
└── iteration-1/
    ├── eval-top-months-chart/
    │   ├── with_skill/{outputs/, timing.json, grading.json}
    │   └── without_skill/{outputs/, timing.json, grading.json}
    └── benchmark.json
```

When improving an existing skill, snapshot it (`cp -r <skill-path> <workspace>/skill-snapshot/`) and use that as the baseline instead of "without skill."

Capture `timing.json` (`total_tokens`, `duration_ms`) per run — a skill that improves quality but triples token cost is a different tradeoff than one that's both better and cheaper.

## Assertions

Add after seeing the first round of outputs, not before. Good assertions are objectively checkable: "output file is valid JSON," "chart has labeled axes," "report has ≥3 recommendations." Weak: "output is good" (too vague), "uses the exact phrase X" (too brittle). Leave subjective qualities (style, "feels right") to human review instead of forcing a bad assertion.

```json
"assertions": [
  "The output includes a bar chart image file",
  "The chart shows exactly 3 months",
  "Both axes are labeled",
  "The chart title or caption mentions revenue"
]
```

## Grading

Grade each assertion PASS/FAIL with concrete evidence (quote/reference the output, not just an opinion). Use a verification script for mechanically-checkable assertions (valid JSON, row counts, file dimensions) — more reliable and reusable than LLM judgment. Use an LLM judge for the rest. Don't give benefit of the doubt: a "Summary" heading with one vague sentence is a FAIL for "includes a summary."

While grading, watch for bad assertions themselves: always-pass (tests nothing), always-fail (broken or too-hard test), or unverifiable from the output alone — fix these before the next iteration.

For comparing two versions, try blind comparison: show both outputs to an LLM judge without revealing which is which, let it score holistic quality on its own rubric.

## Aggregating: `benchmark.json`

```json
{
  "run_summary": {
    "with_skill": { "pass_rate": {"mean": 0.83, "stddev": 0.06}, "time_seconds": {"mean": 45.0}, "tokens": {"mean": 3800} },
    "without_skill": { "pass_rate": {"mean": 0.33}, "time_seconds": {"mean": 32.0}, "tokens": {"mean": 2100} },
    "delta": { "pass_rate": 0.50, "time_seconds": 13.0, "tokens": 1700 }
  }
}
```
`delta` is what the skill costs vs. what it buys. Stddev only means something with multiple runs per eval.

## Analyzing patterns

- Remove/replace assertions that always pass in both configs (tell you nothing).
- Investigate assertions that always fail in both (broken assertion, too-hard case, or wrong target).
- Study assertions that pass with-skill but fail without — that's where the skill demonstrably helps; understand why.
- High stddev across repeated runs on the same eval signals flaky eval or ambiguous instructions — add examples/specificity.
- Investigate time/token outliers via the execution transcript.

## Human review

Assertions only check what you thought to write. Have a human review outputs alongside grades, recording specific actionable feedback per test case ("chart is missing axis labels and months aren't in chronological order" — not "looks bad"). Empty feedback = passed review.

## Iteration loop

Sources of signal: failed assertions (specific gaps), human feedback (broader quality issues), execution transcripts (the *why* — ambiguous instructions the agent ignored, or wasted steps from vague guidance).

Feed all three plus the current `SKILL.md` to an LLM and ask for proposed changes, with these guidelines:
- Generalize from feedback — fix the underlying issue broadly, not a narrow patch for one test case.
- Keep it lean — if pass rates plateau despite adding rules, try removing instructions instead.
- Explain the *why* in instructions ("do X because Y causes Z") rather than bare imperatives — models follow reasoned instructions more reliably.
- Bundle repeated work into `scripts/` if multiple runs independently reinvent the same helper logic.

Loop: propose → apply → rerun in a new `iteration-N+1/` → grade/aggregate → human review → repeat. Stop when feedback is consistently empty or improvement plateaus.

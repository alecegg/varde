# Test skill output

Use tests to check whether a skill improves output across normal and edge-case prompts.

## Test cases: `evals/evals.json`

Each test case: a realistic **prompt**, a human-readable **expected_output**, optional **input files**. Start with 2-3 cases. Add more after the first results. Vary phrasing/formality, include at least one edge case (malformed input, ambiguous request), use realistic context (real file paths, not "process this data").

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
the prompt WITH the skill and, unless `--no-baseline`, WITHOUT it. Optional
verification scripts grade mechanical assertions first. An LLM judge grades
the remaining assertions. The runner writes the `iteration-N/` tree plus
`benchmark.json` with the with/without delta. `--runs N` repeats each config so
stddev is meaningful; `--iteration N` labels the workspace subdir. Repeat
`--eval ID` to rerun selected cases after calibration. This script
measures output quality; `run-evals.sh` measures *triggering*.

Each Claude invocation has a 300-second default limit. Pass
`--timeout-seconds N` to choose another positive limit. Evaluated timeouts
appear in `timing.json`, `grading.json`, and benchmark outcome counts. Judge
timeouts remain separate from evaluated-run timeouts and assertion results.

Add `setup_script` when a case needs repository state. Add
`verification_script` for filesystem, JSON, count, or exact-string assertions.
Both paths are relative to the skill directory. Setup scripts prepare each fresh
sandbox. Verification scripts return the same `results` array as the judge and
may grade any declared assertion. The judge receives only ungraded assertions.

Each run executes in a fresh temporary directory. `--sandbox-dir` supplies a
template copied before every run. Use a disposable standalone clone when Git
history matters. Linked worktrees are rejected because copied `.git` pointers
can mutate the original repository.

The runner spawns roughly `evals × configs × runs × 2` billed calls when every
assertion needs judging. Start discovery with 2-3 evals at `--runs 1`. Use at
least `--runs 3` before making comparative decisions.

Before a release, scope billed evaluations to changed skills:

```bash
scripts/run-changed-output-evals.sh --base <release-ref>
```

The wrapper compares `--base` with `HEAD` by default. Pass `--head <ref>` for
another explicit endpoint. It selects changed directories containing both
`SKILL.md` and `evals/evals.json`, then delegates each selection to
`run-output-evals.sh`. Preview the stable repository-relative selection without
external execution using `--list-only`. Arguments after `--` pass through to
the output runner, such as `-- --runs 3`.

## Running: with-skill vs. without-skill (or vs. previous version)

Run each case in a clean context. Do not reuse state between cases. Organize as:

```
csv-analyzer-workspace/
└── iteration-1/
    ├── eval-top-months-chart/
    │   ├── with_skill/{outputs/, timing.json, grading.json}
    │   └── without_skill/{outputs/, timing.json, grading.json}
    └── benchmark.json
```

When comparing skill versions, snapshot both versions with identical eval files.
Run each snapshot separately using `--no-baseline`. Compare their benchmark
files, then review paired transcripts without version labels.

`timing.json` records duration, complete token categories, total tokens, and
evaluated-agent cost. Total tokens include ordinary input, output, cache
creation, and cache reads. Missing usage becomes `tokens: null`; measured zero
remains `tokens: 0`. Judge usage stays excluded from skill-efficiency metrics.

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

Grade each assertion PASS/FAIL with concrete evidence. Verification scripts
should inspect mechanical outcomes directly. Examples include valid JSON, row
counts, file dimensions, and repository diffs. Use the judge for transcript
behavior and subjective output qualities. Never infer file creation from prose.

While grading, watch for bad assertions themselves: always-pass (tests nothing), always-fail (broken or too-hard test), or unverifiable from the output alone — fix these before the next iteration.

For comparing two versions, try blind comparison: show both outputs to an LLM judge without revealing which is which, let it score overall quality on its own rubric.

## Aggregating: `benchmark.json`

```json
{
  "run_summary": {
    "with_skill": {
      "pass_rate": {"mean": 0.83, "stddev": 0.06},
      "time_seconds": {"mean": 45.0},
      "tokens": {"mean": 3800, "total": 11400, "measured_runs": 3, "unavailable_runs": 0},
      "successful_assertions": {"total": 10},
      "token_efficiency": {"status": "measured", "successful_assertions_per_1000_tokens": 0.8772}
    },
    "without_skill": {
      "pass_rate": {"mean": 0.33},
      "time_seconds": {"mean": 32.0},
      "tokens": {"mean": 2100, "total": 6300, "measured_runs": 3, "unavailable_runs": 0},
      "successful_assertions": {"total": 4},
      "token_efficiency": {"status": "measured", "successful_assertions_per_1000_tokens": 0.6349}
    },
    "delta": {
      "pass_rate": 0.50,
      "time_seconds": 13.0,
      "tokens": 1700,
      "successful_assertions": 6,
      "successful_assertions_per_1000_tokens": 0.2423
    }
  }
}
```
`delta` is what the skill costs versus what it buys. Stddev only means
something with multiple runs per eval. Token efficiency counts successful
assertions for runs with measured usage, normalized per 1,000 tokens. Its
status is `measured`, `partial`, `unavailable`, or `zero_tokens`. `partial`
means some runs lacked usage data. `zero_tokens` means usage was measured,
but division would be undefined.

## Analyzing patterns

- Remove/replace assertions that always pass in both configs (tell you nothing).
- Investigate assertions that always fail in both (broken assertion, too-hard case, or wrong target).
- Study assertions that pass with-skill but fail without — that's where the skill demonstrably helps; understand why.
- High stddev across repeated runs on the same eval signals flaky eval or ambiguous instructions — add examples/specificity.
- Investigate time/token outliers via the execution transcript.

## Manual lifecycle benchmarks

Before major releases, run the scenarios in
`skills/benchmarks/lifecycle-scenarios.json` against a disposable repository.
Validate the catalog before starting:

```bash
skills/benchmarks/validate-lifecycle-scenarios.sh \
  skills/benchmarks/lifecycle-scenarios.json
```

Follow each scenario's setup and workflow actions exactly. Check every
observable assertion, and save artifacts at its evidence paths. Capture usage
metadata at the named token evidence path. Keep transcript artifacts beside
the assertion evidence so release comparisons remain auditable.

## Human review

Assertions check only the requirements you wrote. Have a human review outputs alongside grades, recording specific feedback per test case ("chart is missing axis labels and months aren't in chronological order" — not "looks bad"). Empty feedback means the review passed.

## Iteration loop

Use failed assertions (specific gaps), human feedback (broader quality issues), and execution transcripts. Transcripts explain why the agent ignored an instruction or wasted steps on vague guidance.

Give those three sources and the current `SKILL.md` to an LLM. Ask for proposed changes, using these guidelines:
- Generalize from feedback — fix the underlying issue broadly, not a narrow patch for one test case.
- Keep it lean — if pass rates plateau despite adding rules, try removing instructions instead.
- Explain the *why* in instructions ("do X because Y causes Z") rather than bare imperatives — models follow reasoned instructions more reliably.
- Bundle repeated work into `scripts/` if multiple runs independently reinvent the same helper logic.

Loop: propose → apply → rerun in a new `iteration-N+1/` → grade/aggregate → human review → repeat. Stop when feedback is consistently empty or improvement plateaus.

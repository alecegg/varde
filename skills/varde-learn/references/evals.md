# Skill evaluation and trigger query sets

Use output evals on a stable skill to check whether it improves task results
against a no-skill baseline. This measures output quality; `varde-learn eval
trigger` measures whether the description triggers the skill.
`varde-learn eval output` defaults to Codex with `gpt-6-luna` for both the
evaluated session and judge. Select `--harness claude` explicitly for Claude;
its default model applies unless `--model` is supplied. `--judge-model` overrides
the judge model only. There is no fallback when the selected client/model fails.
Results apply to the selected harness/model, not every supported harness.

Harness runs and judge calls can incur charges. Run no trigger or output
evaluation session until the user explicitly approves the run and its cost;
static checks of JSON, query coverage, and file structure need no session.

## Cases and assertions

Create `evals/evals.json` with realistic prompts, a human-readable
`expected_output`, optional input `files`, and objectively checkable
`assertions`. Start with 2-3 cases incl. an edge case; review outputs before
writing assertions.

## Run and compare

Run `varde-learn eval output <skill-dir> --harness codex --model gpt-6-luna`. Each billed evaluated run and judge
call costs money: with all-judge-graded assertions, expect roughly
`evals × configs × runs × 2` calls. Start with 2-3 cases and one run; use at
least three runs before comparing. Use a disposable standalone clone as the
sandbox when Git history is needed — never a linked worktree. To compare skill
versions, run identical eval files against each snapshot with `--no-baseline`
and compare pass rates, measured token usage, and available cost in `benchmark.json`.
Codex may not report dollar cost; do not interpret unavailable cost as zero. See `varde-learn eval
output --help` for options, schema, and output files.

Changed skills since a ref: `git diff --name-only <base> -- skills | cut -d/ -f2 | sort -u`;
run `varde-learn eval output` on each that has `evals/evals.json`. There is no
changed-skills wrapper — run it per skill by hand.

## Grade and iterate

Put mechanical checks — file creation, valid JSON, counts, dimensions, diffs —
in `verification_script`; the judge grades the rest from the transcript's
final text plus the sandbox's post-run file listing and ordered tool-use
list. Codex runs preserve JSONL events and normalize them for grading. Require
captured reviewer execution and results for independent-review assertions;
prose claims alone are insufficient. If the trace cannot establish an assertion,
report missing evidence rather than awarding PASS. Grade each assertion PASS or
FAIL with concrete evidence; never infer
file creation from prose. Check that assertions are neither always passing,
always failing, nor unverifiable from available output.

## Trigger accuracy

Start with 6-8 realistic prompts labeled `should_trigger: true/false`, covering
likely triggers and close misses that share terms but need a different task;
skip unrelated negatives. Screen with one run per query:

```sh
varde-learn eval trigger <skill-name> <queries.json> --harness <harness> --runs 1
```

For Codex, also pass `--skill-path <absolute-path-to-SKILL.md>` naming the
existing skill file; the substring proxy requires it. For example:

```sh
varde-learn eval trigger <skill-name> <queries.json> --harness codex \
  --skill-path <absolute-path-to-SKILL.md> --runs 1
```

Screen with `--runs 1`; repeat uncertain cases with `--runs 3`. Harness
caveats (Codex's substring proxy, OpenCode's stream quirks): `varde-learn eval
trigger --help`.

Positive cases should pass above 0.5; expand to ~20 prompts × 3 runs only
when misfires persist.

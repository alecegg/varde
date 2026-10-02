# Skill evaluation and trigger query sets

An output eval checks whether a stable skill improves task results against a
no-skill baseline; a trigger eval checks whether its description triggers it.

Harness runs and judge calls can incur charges: run no evaluation session until
the user explicitly approves the run and its cost.

## Cases and assertions

Eval files edit the skill: route them through `varde-change`.

1. Create `evals/evals.json` as `{skill_name, evals:[...]}`, each eval with:
   - `id` and a realistic `prompt`;
   - a human-readable `expected_output`;
   - objectively checkable `assertions`;
   - optional `files`, `setup_script`, and `verification_script`.
2. Start with 2-3 cases, including an edge case.
3. Review outputs before writing assertions.

## Run and compare

Run `varde-learn eval output <skill-dir>`; its `--help` lists options. Results
apply only to the selected harness and model, with no fallback. The command
copies `<skill-dir>` as-is. In the varde repo, a skill with
entries in `skills/shared/MANIFEST` needs `<skill-dir>` pointed at an installed
copy (`skills/install.sh -d <temp-dir> -s <skill>`, then
`<temp-dir>/<skill>`), not the repo directory, so its shared files resolve.

- Budget roughly `evals × configs × runs × 2` billed calls when every
  assertion is judge-graded. Start with one run; use at least three before
  comparing.
- When the run needs Git history, sandbox it in a disposable standalone clone,
  never a linked worktree.
- To compare skill versions, run identical eval files against each snapshot
  with `--no-baseline` and compare pass rates, token usage, and available cost
  in `benchmark.json`. Unavailable cost, common with Codex, is not zero.

## Grade and iterate

- Put mechanical checks (file creation, valid JSON, counts, dimensions, diffs)
  in `verification_script`; the judge grades the rest from the final text, the
  post-run file listing, and the ordered tool-use list.
- Accept a grade only with concrete trace evidence: prose never proves file
  creation or independent-review execution, and an assertion the trace cannot
  establish is missing evidence, not PASS.
- Replace assertions that always pass, always fail, or cannot be verified from
  available output.

## Trigger accuracy

1. Write 6-8 realistic prompts labeled `should_trigger: true/false`: likely
   triggers and close misses that share terms but need a different task. Skip
   unrelated negatives.
2. Screen with one run per query; for Codex, also pass
   `--skill-path <absolute-path-to-SKILL.md>`. `varde-learn eval trigger --help`
   lists harness caveats.

   ```sh
   varde-learn eval trigger <skill-name> <queries.json> --harness <harness> --runs 1
   ```

3. A positive passes when it triggers in more than half its runs; a negative
   passes otherwise. Repeat uncertain cases with `--runs 3`.
4. Expand to ~20 prompts × 3 runs only when misfires persist.

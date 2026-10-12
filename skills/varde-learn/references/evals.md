# Skill evaluation and trigger query sets

An output eval checks whether a stable skill improves task results against a
no-skill baseline; a trigger eval checks whether its description triggers it.

Harness runs and judge calls can incur charges: run no evaluation session until
the user explicitly approves the run and its cost.

## Cases and assertions

Eval files edit the skill: load `varde-change`: use your skill tool, or read `../../varde-change/SKILL.md`, and route them through it.

1. Create `evals/evals.json` as `{skill_name, evals:[...]}`, each eval with:
   - `id` and a realistic `prompt`;
   - a human-readable `expected_output`;
   - judge-graded `assertions`;
   - optional deterministic `assert` fixtures;
   - optional `files`, `setup_script`, and `verification_script`.

| Assertion kind | Required keys |
|---|---|
| `file_contains` | `path`, `contains` |
| `file_absent` | `path` |
| `command_exit` | `command`, `exit_code` |
| `event_order` | `events` |
| `no_write_outside` | `allowed_paths` |

## Calibrate

Add `evals/mutations.json` with a non-empty `mutations` list. Each mutation
has these fields:

- `id`;
- skill-relative `file`;
- a unique, non-empty `remove` span;
- selected `evals`;
- optional `replace_with` and `negative` (set `negative` for a control mutation that removes unrelated text; its selected evals must still pass).

Run `varde learn eval calibrate <skill-dir>` before trusting the suite.
Calibration passes only when each mutation makes its selected evals fail and
the restored skill passes them.

Until calibration passes, treat suite results as diagnostics only, never as a
pass/fail gate.

## Run and compare

Run `varde learn eval output <skill-dir>`; `--help` lists options. Results
apply only to the selected harness and model without fallback, and the command
copies `<skill-dir>` as-is. For a repo skill listed in `skills/shared/MANIFEST`,
sync it in an isolated temporary environment with
`HOME=<temp-dir>/home XDG_CONFIG_HOME=<temp-dir>/xdg VARDE_CONFIG_DIR=<temp-dir>/config CARGO_INSTALL_ROOT=<temp-dir>/cargo VARDE_TOZ_CONFIG_DIR=<temp-dir>/toz
varde setup sync --skills-dir <temp-dir>/skills
--agents-dir <temp-dir>/agents --harnesses none`, then set `<skill-dir>` to
`<temp-dir>/skills/<skill>` so its shared files resolve.

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
   `--skill-path <absolute-path-to-SKILL.md>`. `varde learn eval trigger --help`
   lists harness caveats.

   ```sh
   varde learn eval trigger <skill-name> <queries.json> --harness <harness> --runs 1
   ```

3. A positive passes when it triggers in more than half its runs; a negative
   passes otherwise. Repeat uncertain cases with `--runs 3`.
4. Expand to ~20 prompts × 3 runs only when misfires persist.

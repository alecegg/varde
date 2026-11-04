---
topic: varde-improve/evals-trigger
version: 1
summary: Eval step 6 of 6 - billed, needs the user's explicit cost approval - trigger query sets
---

## Trigger accuracy

1. Write 6-8 realistic prompts labeled `should_trigger: true/false`: likely
   triggers and close misses that share terms but need a different task. Skip
   unrelated negatives.
2. Screen with one run per query; for Codex, also pass
   `--skill-path <absolute-path-to-SKILL.md>`. `varde learn measure <skill> trigger --help`
   lists harness caveats.

   ```sh
   varde learn measure <skill-name> trigger <queries.json> --harness <harness> --runs 1
   ```

3. A positive passes when it triggers in more than half its runs; a negative
   passes otherwise. Repeat uncertain cases with `--runs 3`.
4. Expand to ~20 prompts × 3 runs only when misfires persist.

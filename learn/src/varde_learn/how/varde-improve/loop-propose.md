---
topic: varde-improve/loop-propose
version: 1
summary: Improvement loop steps 2-3, after rank - propose a change, report records for the user's decision
---

## 2. Propose

Propose one skill or step at a time:

- `varde learn skills extract <skill> [<step>]` moves a step into a counted tool (no step: list the step names).
- `varde learn skills reset <skill> --model <id> --harness-version <v>` slims the skill to outcomes plus validation and moves the rest to on-request topics. Add `--no-pointer` to leave no `## Topics` section or `how:` line (a baseline).
- `varde learn skills reset <skill> --to-baseline --baselines <dir> [--gen <g>] [--root <pkg root>]` restores the exact baseline file set from `slim/`. It takes no `--model` and deletes extra files. It is refused when the copy does not hash to the entry's `tree_hash`.

Each writes a record under the memory root `loop/` with the diff and the whole-route token delta; add `--dry-run` to preview. No file changes yet.

## 3. Report

`varde learn skills report` lists the records and writes a page with one decision block per open proposal. The user answers on the page. Read the answers with `varde learn docs comments <page> --kind decision`.

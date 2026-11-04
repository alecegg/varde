---
topic: varde-orchestrate/pipeline-review
version: 1
summary: Enqueue the plan-level review, handle pass and findings, and integrate
---

# Pipeline review

- When all task items are done, enqueue the one plan-level review with `varde plan queue enqueue --plan-dir <plan-dir> --id <plan>-plan-review --role reviewer --kind review --owned-file <path>... --depends-on <task item>...`. Use one `--owned-file` per task owns entry (or `**`) and one `--depends-on` per task item.
- The reviewer reports `pass <id>` or `findings <id>` with `--notes <report>` to you. Finish a pass with `--outcome done` and findings with `--outcome findings`, which enqueues a builder fix in the plan worktree.
- After the fix, enqueue the fixes-only re-check with the same flags plus `--id <plan>-plan-review-recheck --parent <plan>-plan-review` (depth 2, within the cap of 3).
- Integrate passed work through `references/build-finish.md`.

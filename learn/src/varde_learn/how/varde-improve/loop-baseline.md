---
topic: varde-improve/loop-baseline
version: 1
summary: Improvement loop step 6, last - record, fill and verify a no-how baseline
---

## 6. Baseline

- Record one with `varde learn measure <skill> baseline --record --gen <g> --source <checkout> --baselines <dir>` (files, how topics, `tree_hash`, `slim/` copy).
- Against a checkout with `core/`, topics the SKILL.md does not point at are added to `core/how-unpointed.txt`, which the repo ref check reads, so commit it.
- After an add-back is committed, log it with `skills fill <skill> --baselines <dir> --step <s>|--path <p> --evidence <friction id>... --form text|how-line --source <checkout>`. A re-added step gets a new id that `supersedes` the old one.
- `skills fill <skill> --baselines <dir> --retire <id|all>` ends fills (kept, never deleted, also across reset and accept).
- `skills fill <skill> --baselines <dir> --history` lists all fills, retired included.
- Verify with `measure <skill> baseline --source <checkout> --check` (exit 1 on drift or a tree-hash mismatch).
- File how-skip friction with `--target how/<skill>/<step>` so demand and fills can join it.

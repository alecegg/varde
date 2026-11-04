---
topic: varde-improve/distill-apply
version: 1
summary: Distill steps 6-8 after approval - billed evals only if approved - apply change, record adoption
---

6. If evals were approved, run the evals outcomes' cases first
   (`varde learn measure <skill-dir> output`) as the "before" run.
7. Load the planning skill when scope is unsettled; otherwise load the build
   skill for a bounded edit (micro-change route). If evals were approved, rerun
   the same cases and compare results.
8. After applying the approved change, record one adoption for its source items:

   ```sh
   varde learn friction adopt --items 42,43 \
     --summary "Added the approved path check" \
     --files "skills/example/SKILL.md,skills/example/references/check.md" \
     --commit abc123 --eval-before before/benchmark.json \
     --eval-after after/benchmark.json --json
   ```

# Distill recurring friction into an approved improvement

Run this workflow only when the user asks to review recurring friction.

1. Search open items and inspect every relevant page:

   ```sh
   varde-learn friction list --status open --json
   ```

   Read likely candidates with `varde-learn friction show <ID> --json`.
2. Require at least two real occurrences of the same obstacle, on one item or
   across matching items, with a shared improvement target. Verify the
   occurrence evidence and recorded context. If there is only one occurrence
   or the events do not share a cause and target, report that the evidence is
   insufficient and propose nothing.
3. Inspect the relevant source and existing guidance. Classify the proposed
   change as adding a missing rule, tightening an underspecified rule, or
   simplifying/removing a rule that is ignored, contradicted, or obsolete.
   Prefer a small source change over repeating guidance more loudly.
4. Present, and offer a before/after evaluation on identical cases:
   - source item IDs and each occurrence's evidence;
   - the shared failure mode;
   - exact target files or symbols and the proposed diff;
   - expected impact as a hypothesis, and risks;
   - items that would become `promoted`.
5. Ask for approval of (a) the exact source scope, including installed copies,
   and (b) billed eval runs with cost (`references/evals.md`); the request to
   review friction implies neither.
6. If evals were approved, run the cases from `references/evals.md` first, as
   the "before" run.
7. Apply the approved source change through
   `varde-change build` (micro-change route). If evals were approved, rerun
   the same cases and compare results.
8. After applying the approved source change, record one adoption for its source
   items:

   ```sh
   varde-learn adopt record --items 42,43 \
     --summary "Added the approved path check" \
     --files "skills/example/SKILL.md,skills/example/references/check.md" \
     --commit abc123 --eval-before before/benchmark.json \
     --eval-after after/benchmark.json --json
   ```

- Include `--commit` only for a verified commit, and eval paths only for
  approved, completed runs.
- Recording promotes every listed item and appends its status history in one
  transaction, so run no separate status command; report a failure.

# Distill recurring friction into an approved improvement

Run this workflow only when the user asks to review recurring friction. One
incident can be recorded, but it cannot support a change proposal.

1. Search open items and inspect every relevant page:

   ```sh
   varde-learn friction list --status open --json
   ```

   Follow `meta.next_offset` while `meta.truncated` is true, then read likely
   candidates with `varde-learn friction show <ID> --json`; finish all show
   pages before counting occurrences.
2. Require at least two real occurrences of the same obstacle, on one item or
   across matching items, with a shared improvement target. Verify the
   occurrence evidence and recorded context. If there is only one occurrence
   or the events do not share a cause and target, report that the evidence is
   insufficient and propose nothing.
3. Inspect the relevant source and existing guidance. Classify the proposed
   change as adding a missing rule, tightening an underspecified rule, or
   simplifying/removing a rule that is ignored, contradicted, or obsolete.
   Prefer a small source change over repeating guidance more loudly.
4. Present the source item IDs, evidence for each occurrence, shared failure
   mode, exact target files or symbols, proposed diff, expected impact as a
   hypothesis, risks, and which items would become `promoted`. Offer a
   before/after evaluation using identical cases; explain that billed runs
   require separate explicit approval.
5. Ask for approval of the exact source scope and installed copies. Separately
   ask for explicit approval of billed eval runs and their cost; do not infer
   either approval from the request to review friction. If source changes are
   approved, read `evals.md` and run the before cases only when evals are also
   approved. Then run the `varde-change build` workflow. If evals are declined,
   continue the approved source workflow without them. For skill or agent-
   document changes, have the proposed diff reviewed with
   `varde-agent-doc-authoring` before applying it.
6. If evals were approved, use `evals.md` to run the same cases after the
   source change and compare results.
7. After applying the approved source change, record one adoption for its source
   items:

   ```sh
   varde-learn adopt record --items 42,43 \
     --summary "Added the approved path check" \
     --files "skills/example/SKILL.md,skills/example/references/check.md" \
     --commit abc123 --eval-before before/benchmark.json \
     --eval-after after/benchmark.json --json
   ```

`--items` and `--files` are comma-separated. Include `--commit` when the
change has a verified commit. Include eval paths only when those runs were
separately approved and completed; the CLI validates and stores the JSON file
contents, not their paths. Recording the adoption promotes every listed item
and appends its status history in one transaction, so do not run a separate
status command. If recording fails, report the failure; no partial adoption or
promotion is written.

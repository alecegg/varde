---
topic: varde-plan/plan-set
version: 1
summary: Split independently shippable changes into a plan set
---

A plan set is a folder of plans that `varde plan status` shows together,
ordered by plan-level `depends_on`. Review and merge each plan on its own, with
user approval. Use it at Finalize step 2.

1. List candidate titles and dependency order; ask whether any should be
   combined or split differently, then wait.
2. Create the set as a folder under `<working>/plans/`, each plan at
   `<set>/<slug>/plan.md`, finalized with the Finalize steps.
3. Delete the parent's task files and set its status to `cancelled`.

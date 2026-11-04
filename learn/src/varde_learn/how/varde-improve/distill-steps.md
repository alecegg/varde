---
topic: varde-improve/distill-steps
version: 2
summary: Distill steps 1-5, up to the user's approval; steps 6-8 apply the change
---

1. Search open items:

   ```sh
   varde learn friction list --status open --json
   ```

2. Inspect likely candidates with `varde learn friction show <ID> --json`.
   Check for two real occurrences of the same obstacle and a shared improvement
   target.
3. Inspect the relevant source and existing guidance. Classify the proposed
   change and state which of these it is:
   - adding a missing rule;
   - tightening an underspecified rule;
   - relaxing or removing a rule, gate, or required step.

   Weigh relaxing before tightening, and apply the option and audit rules in
   `references/options.md`.
4. Present these:
   - source item IDs and the shared failure mode;
   - exact targets and diff;
   - impact and risks;
   - items to promote.

   Offer a before/after evaluation on identical cases.
5. Ask for approval of the exact source scope and of billed eval runs with cost.

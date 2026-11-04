---
topic: varde-plan/finalize-checks
version: 1
summary: Run the Finalize checks (validate, decompose, lint, page components) before the independent review
---

1. Run `varde plan validate <plan.md> --json` and fix diagnostics.
2. Decompose into tasks using `references/plan-decomposition.md`; use a plan set
   for several independently shippable changes (topic `plan-set`).
3. Run `varde learn check <plan.md> <task.md>...`; fix errors and leave warnings unfixed.
4. Show planned data and screens as `ui` components (`varde learn docs blocks`), then
   run `varde learn check <plan.md>`.

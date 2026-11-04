---
topic: varde-improve/evals-calibrate
version: 1
summary: Eval step 2 of 6 - billed, needs the user's explicit cost approval - calibrate with mutations
---

## Calibrate

Add `evals/mutations.json` with a non-empty `mutations` list. Each mutation
has these fields:

- `id`;
- skill-relative `file`;
- a unique, non-empty `remove` span;
- selected `evals`;
- optional `replace_with` and `negative` (set `negative` for a control mutation that removes unrelated text; its selected evals must still pass).

Run `varde learn measure <skill-dir> calibrate` before trusting the suite.
Calibration passes only when each mutation makes its selected evals fail and
the restored skill passes them.

Until calibration passes, treat suite results as diagnostics only, never as a
pass/fail gate.

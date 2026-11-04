---
topic: varde-build/debug-loop
version: 1
summary: Build the repro loop, test hypotheses, tag debug logs, add the regression test
---

1. Build one fast, deterministic pass/fail command that asserts the user's
   exact symptom; run it and use it for bisection and hypothesis testing.
   If it cannot be reproduced locally, see debug-no-repro.
2. Confirm the loop produces the failure the **user** described, not a nearby
   one. Minimize to the smallest red scenario.
3. State a falsifiable hypothesis before testing it. An untested hypothesis
   does not support a fix. If evidence does not isolate the cause or the first
   test fails, add distinct alternatives and rank them by supporting evidence.
4. Tag every debug log with a unique prefix.
5. Write the regression test at a seam that exercises the bug as it occurs at
   the call site. A one-caller test can pass while other callers fail. Watch it fail, apply the fix, watch it pass, and rerun the step 1
   loop against the original scenario.

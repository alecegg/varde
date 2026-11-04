---
topic: varde-build/mode-and-wrap-up
version: 1
summary: Name the debug mode in plain words; find leftover debug instrumentation by its prefix
---

- Name the mode to the user in plain words, such as "Diagnosing only; I won't
  change code".
- Before declaring done, `grep` the `[DEBUG-...]` prefix to find leftover
  instrumentation.

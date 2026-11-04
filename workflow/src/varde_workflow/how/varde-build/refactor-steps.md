---
topic: varde-build/refactor-steps
version: 1
summary: Change one behavior-preserving step at a time; find callers of an internal API
---

- Make one behavior-preserving change at a time. Rerun the target's tests after
  each.
- Replacing an internal API: find callers with `varde map dependents`; shim
  external consumers only.

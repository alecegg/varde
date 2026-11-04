---
topic: varde-orchestrate/pipeline-eligibility
version: 1
summary: Start gates, item eligibility, and what blocks new starts
---

# Pipeline eligibility

- Check `varde plan queue status` for ready items and free budget, then launch workers while both allow more work. There are no per-role caps. Independence and the global resource budget govern starts; the global worker ceiling is the backstop.
- An item is eligible only when:
  - its owned files do not overlap in-flight work;
  - its dependencies are merged;
  - its `serialize_with` partners are idle;
  - its worktree is distinct.
- Missing or stale resource data and exceeded budget limits block new starts.

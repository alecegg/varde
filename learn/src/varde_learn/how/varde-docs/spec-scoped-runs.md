---
topic: varde-docs/spec-scoped-runs
version: 1
summary: Regenerate only named domains, such as a plan's linked specs
---

Given specific domains (e.g. the plan's linked specs):

- Regenerate only those domain documents; skip full domain discovery and
  workflow step 4.
- Still read other domain roots for overlap and `unclassified_paths`
  classification.
- Still refresh a stale architecture document; "only <domain>" limits domain
  documents. Only an explicit user ban on architecture edits leaves it stale;
  report that.
- Report whether architecture was written or left unchanged.

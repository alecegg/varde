---
topic: varde-verify/verify-ui
version: 1
summary: Browser-tool rules for UI acceptance checks
---

## UI checks

A UI check needs a browser tool from your tool list (harness tools are not on
`PATH`); without one it is `unavailable`, never passed. Never infer
rendering from source or HTTP. Use only user-supplied credentials and submit no
form that changes real data.

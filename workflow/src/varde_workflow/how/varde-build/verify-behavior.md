---
topic: varde-build/verify-behavior
version: 1
summary: Check expected values, the user-facing seam, and retries; reproduce a claimed pre-existing failure
---

- Compare check results with independent expected values.
- For behavior changes, check the user-facing seam (installed form when one
  exists) and show the check fails when broken.
- Retryable writes: run twice and compare final state.
- Reproduce a failure the task calls pre-existing at the prerequisite commit.

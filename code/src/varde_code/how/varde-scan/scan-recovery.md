---
topic: varde-scan/scan-recovery
version: 1
summary: Recover an incomplete scan and restore index readiness
---

- Read diagnostics and repair their cause before claiming the scan is complete.
- For intentionally malformed fixtures, use repository `.ignore` entries and record the excluded scope. Suppressions do not clear diagnostics.
- For `index_missing` or `index_stale`, follow the index readiness steps (scan on the main checkout; workers never build). If readiness cannot be restored, report the scan as unavailable and state the lost capability.

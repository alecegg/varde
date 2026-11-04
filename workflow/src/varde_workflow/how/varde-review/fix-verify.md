---
topic: varde-review/fix-verify
version: 1
summary: Batch checks and re-check after fixes
---

## Fix verification

### Check the batch

- Run the type check and tests once per touched package (the full repo for a cross-package fix). On failure, repair and rerun: at most two repair rounds, then record the failing checks and leave those findings `open`.
- Confirm each fixed defect is gone before `fixed`: prefer a check that failed before the fix.

### Re-check

A behaviour-changing fix gets one fixes-only re-review; new findings block only if high severity. Any other fix gets a header-only re-check: confirm the diff since the old `head` holds only the named fixes and rewrite `head` (`references/report-format.md`).

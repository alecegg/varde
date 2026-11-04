---
topic: varde-learn/recurrence-steps
version: 1
summary: Ordered steps to read and report adoption recurrence
---

1. Read recurrence results with:

   ```sh
   varde learn friction recurrence --json
   ```

2. Report each row's adoption ID and summary, friction item, and later
   occurrence timestamp and evidence. Report `meta.skipped_invalid_timestamps`;
   omitted relative or unsupported dates establish neither recurrence nor its
   absence.
3. An empty result means no recurrence is recorded. Investigate current source
   before proposing a change; do not revert automatically.

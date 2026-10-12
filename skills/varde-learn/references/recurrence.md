# Check adoption recurrence

After an improvement ships, check whether the friction recurred. This reports
historical occurrences; it does not establish that the issue is still present.

1. Read the bounded result pages:

   ```sh
   varde learn adopt recurrence --json
   ```

2. For each row, report its `adoption_id` and `summary`, the friction `item`,
   and the later occurrence's timestamp and evidence.
3. Report `meta.skipped_invalid_timestamps`: those relative (such as `now`) or
   unsupported timestamps were omitted, so infer neither recurrence nor its
   absence from them.
4. Run this after recording an adoption with `varde learn adopt record`; an
   empty result means no recurrence is recorded. Investigate current source
   before proposing a change; do not revert automatically.

# Check adoption recurrence

This check reports historical occurrences; it does not establish that the issue
is still present.

1. Read all bounded result pages:

   ```sh
   varde-learn adopt recurrence --json --limit 100
   ```

   While `meta.truncated` is true, repeat with `--offset` set to
   `meta.next_offset`.
2. For each row, report its `adoption_id` and `summary`, the friction `item`,
   and the later occurrence's timestamp and evidence.
3. Report `meta.skipped_invalid_timestamps`: those relative (such as `now`) or
   unsupported timestamps were omitted, so infer neither recurrence nor its
   absence from them.
4. Offer to investigate the current source and evidence before proposing a
   change. Never revert automatically.

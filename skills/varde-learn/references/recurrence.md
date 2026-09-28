# Check adoption recurrence

Run this when checking whether friction appeared again after an adopted change.
It reports historical occurrences; it does not establish that the issue is
still present.

1. Read all bounded result pages:

   ```sh
   varde-learn adopt recurrence --json --limit 100
   ```

   While `meta.truncated` is true, repeat with `--offset` set to
   `meta.next_offset`. The limit is 1 to 1000.
2. For each row, report its `adoption_id` and `summary`, the friction `item`,
   and the later occurrence's timestamp and evidence. Each occurrence is
   paired with the latest parseable adoption strictly before it. With multiple
   adoptions, an occurrence after an older adoption but before a newer one is
   attributed to the older adoption.
3. Report `meta.skipped_invalid_timestamps`. Those linked adoption or
   occurrence timestamps were relative (such as `now`) or otherwise unsupported
   and were omitted; do not infer recurrence or no recurrence from them. Fixed
   timestamps beginning with `YYYY-MM-DD` are parsed by SQLite. Date-only
   legacy dates compare at midnight UTC, and parseable timezone offsets compare
   as instants. An occurrence equal to an adoption is not later than that
   adoption, but may still follow an earlier adoption.
4. Offer to investigate the current source and evidence before proposing a
   change. Never revert automatically.

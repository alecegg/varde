# Check adoption recurrence

After an improvement ships, check whether the friction recurred. This reports
historical occurrences; it does not establish that the issue is still present.

- Run `varde learn friction recurrence --json`.
- Report each row's adoption ID and summary, friction item, and later occurrence timestamp and evidence.
- Report `meta.skipped_invalid_timestamps`; omitted relative or unsupported dates establish neither recurrence nor its absence.
- An empty result means no recurrence is recorded. Investigate current source before proposing a change; do not revert automatically.

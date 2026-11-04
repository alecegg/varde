# Capture from a completed diagnosis

## Capture eligible incidents

- An event with `current` or `unknown` overlap is eligible for capture only
  when its source identity and historical context are revalidated. It must also
  precede the verified pre-orchestration cutoff. Otherwise leave it
  report-only.
- Other overlaps keep the eligibility rules in `references/diagnose.md`
  (Report rules).
- Capture each distinct eligible incident once with `varde learn sessions capture`
  against the exact frozen `--snapshot` bundle. Use one canonical
  triggering event and no duplicate of an existing friction item. If its witness
  boundary or item grouping is ambiguous, record the finding in the report
  instead.
- A failed-tool candidate is proven by its exact anchored native tool result; a
  normalized status label or excerpt alone does not prove failure.
- `--kind` is `failed-tool`, `repeated-work`, or `workflow-deviation`.
- The item is an existing `--item-id`, or a new one from `--item-source` and `--item-title`. OpenCode family bundles, and any `diagnose_record_ambiguous` error, need `--native-id` from the record anchor.
- Each `created` or `already-recorded` result is recorded in the report with its
  summary refreshed; conflicts and typed validation errors are not successful
  captures.

## Witness identity

- Capture checks one witness across incident kinds, so never relabel an event
  to add an occurrence.

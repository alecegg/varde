# Capture from a completed diagnosis

## Capture eligible incidents

- An individual event can still be eligible for capture only when its source
  identity and historical context are revalidated and it precedes a verified
  pre-orchestration cutoff; otherwise leave it report-only.

For each distinct eligible incident:

1. Confirm no matching friction item already represents it.
2. Pick one canonical triggering event. If the witness boundary or item
   grouping is ambiguous, record the finding in the report instead.
3. For a failed-tool candidate, inspect the exact anchored native tool result;
   a normalized status label or excerpt alone does not prove failure.
4. Choose `--kind` exactly one of `failed-tool`, `repeated-work`, or
   `workflow-deviation`, and the friction item: `--item-id <ID>` for an
   existing item, or `--item-source` and `--item-title` (plus optional
   `--item-target`) for a new one. Take `--source-id` and `--record-index`
   from the inspect record of the frozen bundle.
5. Run:

   ```sh
   varde-learn diagnose capture --snapshot <the exact --snapshot-out path> \
     --source-id <id> --record-index <n> --kind failed-tool \
     --item-source varde-change --item-title "<title>" \
     --evidence "<what the anchored result shows>" --json
   ```

   The CLI copies the whole anchor from the bundle record. Add
   `--native-id <data.records[i].anchor.native_id>` for OpenCode family
   bundles, where parent and child sessions share a source ID and indexes
   repeat, or after a `diagnose_record_ambiguous` error.
6. Record each `created` or `already-recorded` result in the report and
   refresh the final report summary, so a partial run can be retried safely.
   A conflict or typed validation error is not a successful capture.

## Witness identity

- Capture checks one witness across incident kinds, so never relabel an event
  to add an occurrence.

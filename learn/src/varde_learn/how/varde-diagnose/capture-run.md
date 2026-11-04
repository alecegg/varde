---
topic: varde-diagnose/capture-run
version: 1
summary: 2 of 2 - run sessions capture for an eligible incident, record each result in the report
---

# Run the capture

4. Run:

   ```sh
   varde learn sessions capture --snapshot <the exact --snapshot-out path> \
     --source-id <id> --record-index <n> --kind failed-tool \
     --item-source varde-build --item-title "<title>" \
     --evidence "<what the anchored result shows>" --json
   ```

   The CLI copies the whole anchor from the bundle record. Add `--native-id <data.records[i].anchor.native_id>` for OpenCode family bundles, where parent and child sessions share a source ID and indexes repeat, or after a `diagnose_record_ambiguous` error.
5. Record each `created` or `already-recorded` result in the report and refresh its summary.

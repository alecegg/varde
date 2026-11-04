---
topic: varde-diagnose/current-steps
version: 1
summary: 1 of 2 - write cutoff.json, re-inspect; cutoff_verified must be true before analysis
---

Set a cutoff before analyzing current or unknown evidence:

1. Write `cutoff.json` from the diagnosis-request record, or another explicit native anchor that predates orchestration. Use this shape:

   ```json
   {
     "source_path": "<data.sources[i].canonical_path>",
     "record_anchor": {
       "source_id": "<data.records[i].anchor.source_id>",
       "record_index": 17,
       "byte_start": 12345,
       "byte_end": 12567,
       "record_digest": "<data.records[i].anchor.record_digest>",
       "native_id": "<data.records[i].anchor.native_id>"
     }
   }
   ```

   Copy the entire actual anchor object from inspection; the example shows JSONL fields. OpenCode anchors may add `session_id`, `storage_sequence`, and `context_digest`; preserve `native_id` as JSON `null` when inspection returned it.
2. Inspect again with a new `--snapshot-out` and `--cutoff-anchor <cutoff.json>`.
3. Check that `data.coverage.cutoff_verified` is true.

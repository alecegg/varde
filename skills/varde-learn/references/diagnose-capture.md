# Capture from a completed diagnosis

Load only after `references/diagnose.md` has produced a saved report and
verified bounded evidence for an incident to record.

## Capture eligible incidents

An individual event can still be eligible for capture only when its source
identity and historical context are revalidated and it precedes a verified
pre-orchestration cutoff; otherwise leave it report-only.

Save the report first. Then capture each distinct eligible incident only after
checking that it is not already represented by a matching friction item. Use
one canonical triggering event per incident; if the witness boundary or item
grouping is ambiguous, record the finding in the report and do not capture it.
Capture records an occurrence; it does not resolve, promote, or otherwise
change an item's status. Never invent event time, cwd, repository root, HEAD,
or a native identifier from the current checkout or report prose.

The capture file is strict JSON: unknown fields are rejected, and the file is
limited to 64 KiB with `evidence` limited to 8 KiB. Copy `snapshot_digest`,
`session.thread_id`, and the selected `records[i].anchor` from the inspect
output. The anchor has `source_id`, `record_index`, `byte_start`, `byte_end`,
`record_digest`, and `native_id`; the selected file must match the frozen
bundle. Choose one primary `incident_kind`. `item` is either an existing
numeric item ID or a new item with a source, title, and optional target:

```json
{"mode":"existing","id":42}
```

```json
{
  "snapshot_path": "<the exact --snapshot-out path>",
  "snapshot_digest": "<data.snapshot.digest>",
  "session_id": "<data.session.thread_id>",
  "anchor": {
    "source_id": "<data.records[i].anchor.source_id>",
    "record_index": 17,
    "byte_start": 12345,
    "byte_end": 12567,
    "record_digest": "<data.records[i].anchor.record_digest>",
    "native_id": "<data.records[i].anchor.native_id>"
  },
  "incident_kind": "failed-tool",
  "item": {
    "mode": "new",
    "source": "varde-change",
    "title": "Observed retry loop after a failed command",
    "target": "skills/example/SKILL.md"
  },
  "evidence": "The anchored tool result reports a failed command after two identical retries."
}
```

Run `varde-learn diagnose capture --file <incident.json> --json`. Supported
incident kinds are exactly `"failed-tool"`, `"repeated-work"`, and
`"workflow-deviation"`.
For a failed-tool candidate, inspect the exact anchored native tool result;
do not rely on a normalized status label or excerpt alone as proof of failure.
The snapshot digest detects edits to the bundle but does not authenticate its
contents.

The versioned JSON envelope returns `data.disposition` (string `"created"` or
`"already-recorded"`), `item_id`, `occurrence_id`, original `at` and `cwd`, plus
`repo_root` and `head_sha`. This capture path currently returns null for the
last two and does not infer them from today's working tree. An identical retry
returns the existing IDs; a conflict or typed validation error is not a
successful capture. Record each `created` or `already-recorded` result in the
report and refresh the final report summary so a partial report/capture run can
be retried safely.

```json
{"data":{"disposition":"created","item_id":42,"occurrence_id":81,"at":"<event time>","cwd":"<event cwd>","repo_root":null,"head_sha":null}}
```

Historical identity is separate from the snapshot digest and report path.
Prefer a verified native event ID. Where the source provides no such ID, the
approved fallback is an independently revalidated, append-stable JSONL line
position and record digest; never fabricate a native ID. Rewritten, inherited,
or otherwise uncertain anchors remain report-only. Capture checks the same
witness across incident kinds, so do not relabel one event to create another
occurrence. Stable identity makes a retry idempotent; it does not prove that
two separate events have the same natural-language cause.

The friction store is a user-local SQLite database. Schema 3 adds versioned
incident provenance for captured occurrences; migration preserves existing
items and occurrences without inventing provenance for them. Markdown export
uses `varde-friction-item` version 1 and includes provenance when present;
import validates and preserves that field. Legacy imports remain
unprovenanced. Export/import do not transfer the adoption ledger, item links,
target-file/commit metadata, stored eval JSON, or recurrence attribution.
Review exports for private evidence before sharing.

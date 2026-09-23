# Machine-output contract

## Scope

Every machine-readable `varde-code` command returns one JSON object. This
includes query modes, `scan`, `test`, maintenance commands, and watcher
management. `nav_map --format text` is the sole text-mode exception.

## Envelope

```json
{
  "schema_version": 1,
  "ok": true,
  "outcome": "success",
  "data": { "...": "command payload" },
  "meta": { "compact": true, "truncated": false }
}
```

`schema_version` identifies this envelope contract. It is currently `1`.
`ok` reports execution success only. It does not report scan policy success.
`outcome` gives the caller a stable result classification. Query success uses
`success`. Scan outcomes are `passed`, `code-quality-error`, and
`analysis-incomplete`. Tool failures use `tool-error`. `data` holds the
command result.
`meta.compact` reports the active compact policy. `meta.truncated` reports a
declared omission. Truncated results also include recovery metadata.

Failures retain this shape:

```json
{
  "schema_version": 1,
  "ok": false,
  "outcome": "tool-error",
  "data": {
    "error": {
      "code": "invalid_input",
      "message": "input is not valid JSON: ..."
    }
  },
  "meta": { "compact": false, "truncated": false }
}
```

Callers branch on `outcome` first. Then inspect `ok` and `data.error.code`.
The message provides user-facing context. Query errors use the envelope and
remain process-successful. `scan` and `test` return nonzero for tool errors or
CI-gate conditions. They print an envelope first. Panics use stderr and a
nonzero status.

## Scan policy state

Successful scans expose analysis and gate state independently:

```json
{
  "schema_version": 1,
  "ok": true,
  "outcome": "code-quality-error",
  "data": {
    "analysis": {
      "status": "complete"
    },
    "gate": {
      "status": "fail",
      "blocking_findings": 1,
      "diagnostic_count": 0,
      "blocking_diagnostic_count": 0
    },
    "diagnostics": [],
    "findings": [],
    "policy": {
      "mode": "severity-threshold",
      "severity_threshold": "error",
      "active_rule_count": 34,
      "gating_rule_count": 27,
      "sources": { "builtin": 34, "override": 0, "custom": 0 },
      "fingerprint": "..."
    }
  },
  "meta": { "compact": true, "truncated": false }
}
```

`analysis.status` is `complete` or `incomplete`. `gate.status` is `pass`,
`fail`, or `unknown`. An incomplete analysis never certifies a pass. If an
incomplete analysis also finds blocking findings, `gate.status` remains
`fail`; `data.outcome_reasons` lists both `code-quality-error` and
`analysis-incomplete`. `data.outcome` mirrors the top-level scan outcome for
library consumers. The top-level `outcome` selects the primary caller-facing
result.

`gate.diagnostic_count` counts every normalized diagnostic.
`gate.blocking_diagnostic_count` counts diagnostics that prevent certification.
Each diagnostic uses the additive common fields `kind`, `message`, `location`,
`severity`, and `blocking`. `kind` is the stable discriminator. Legacy fields
remain available for compatibility.

`policy` identifies the evaluated rule set. `mode` is either
`severity-threshold` or `selected-rules`. It includes active and gating rule
counts, source counts, and a stable `fnv1a64` fingerprint. The fingerprint
covers active rule definitions, overrides, and gate selection. Store it with
scan results when comparing results across runs.

## Compact payload policy

Commands with `repoRoot` or `rulesDir` emit known repository paths as relative
by default. This avoids repeated absolute prefixes. Set `absolutePaths: true`
to retain them. External paths, source text, and `dbPath`-only calls stay
unchanged. Relative file paths round-trip into query modes.

Spans carry `start_line` and `end_line` by default. Set
`includeSpanDetail: true` to also receive `start_byte`, `end_byte`,
`start_col`, and `end_col`.

Dense outputs prefer summaries. `build` reports `changedFilesCount` and
`changedFilesSample` by default. `--changed-files` returns every path.
`nav_map` applies a per-section token budget. Its flows can report
`childrenOmitted` instead of repeating a large call tree.

`scan` bounds findings by default. The default limit is 100 findings. The
`findings_summary` object reports `total`, `shown`, `truncated`, `by_rule`,
`by_severity`, and the active `offset`. Pass `fullFindings: true` to request
every finding. Use `findingsLimit` and `findingsOffset` for bounded pages.
Full mode is intended for archival output and offline triage.

## Truncation

Omission is explicit. A truncated `nav_map` includes
`data.guide.truncated` entries shaped as:

```json
{
  "section": { "shown": 12, "total": 54, "more": "follow-up query" }
}
```

`shown` and `total` quantify the omission. `more` names the recovery route.
`meta.truncated` is true when this guide is populated. Consumers preserve
these fields when forwarding partial results.

Scan truncation uses the same recovery principle. A bounded result sets
`meta.truncated` to `true` and includes a `data.guide.truncated.findings`
entry:

```json
{
  "shown": 100,
  "total": 542,
  "offset": 0,
  "limit": 100,
  "next_offset": 100,
  "request": "set findingsOffset to next_offset, or set fullFindings to true"
}
```

`shown` and `total` quantify the omission. `next_offset` and `request` name
the recovery route. `findingsOffset` retrieves the next page. `fullFindings`
retrieves the complete list. Consumers must not treat a truncated finding list
as complete.

## Text exception

`nav_map --format json` is canonical machine output. `nav_map --format text`
renders the same result for people. It can use headings and text guidance.
Tools must use JSON when parsing or composing results.

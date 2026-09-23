---
type: flow
description: Analyzes one Varde session with run-scoped transcript consent and separately authorized redacted exports.
---

# Varde session diagnostics flow

Install the optional diagnostics pack when session analysis is needed:

```sh
skills/install.sh --pack diagnostics
```

## Analyze the current session

Diagnostics reads the current transcript by default. Pass a transcript path or
set `VARDE_CURRENT_SESSION_TRANSCRIPT`. The Markdown report names unavailable
access instead of fabricating findings. Findings cite transcript line numbers.

Diagnostics covers routing, plan deviations, repeated work, and evidence
quality. It remains analytical and does not edit skills or production source.

## Read a historical session

Historical access requires all three values:

1. `--source historical`
2. `--session-id <id>`
3. `--historical-consent`

Consent is run-scoped. It expires when that diagnostic process ends. A later
run must request fresh consent. Without consent, the transcript is not read.

## Export a scrubbed bundle

Export consent is separate from transcript consent. Use `--export-consent` with
`--export-dir` only when a bundle is authorized. Configure sensitive literals
with repeated `--redact-pattern` options. The bundle includes the report,
transcript, and NOTICE.md.

NOTICE.md discloses residual risk. Configured patterns are redacted, but
complete secret removal is not guaranteed. Without export consent, no export
directory is created.

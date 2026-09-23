---
name: varde-diagnose
description: "Diagnose one Varde session with cited findings and consent-bounded exports."
---

# Diagnose a Varde session

Use the bundled runner to analyze one transcript. The current session is the
default source. Historical sessions require an identifier and fresh,
run-scoped consent. Consent is never reused by a later run.

## Analyze

Provide a transcript path, or set
`VARDE_CURRENT_SESSION_TRANSCRIPT`. Write a Markdown report with:

```sh
python3 scripts/diagnose-session.py \
  --transcript /path/to/session.log \
  --report /path/to/report.md
```

Reports identify unavailable transcript access instead of fabricating findings.
Findings cite transcript line numbers. Diagnostics remains analytical and does
not edit skills or production source.

## Historical access

Historical reads require `--source historical`, `--session-id`, and
`--historical-consent`. Consent lasts for that process only. A later run must
request consent again.

## Export

Export consent is separate from transcript consent:

```sh
python3 scripts/diagnose-session.py \
  --transcript /path/to/session.log \
  --report /path/to/report.md \
  --export-dir /path/to/export \
  --export-consent \
  --redact-pattern 'secret-value'
```

Configured patterns are redacted from the exported report and transcript. The
bundle includes NOTICE.md, which discloses residual secret-removal risk.
Without export consent, no export directory is created.

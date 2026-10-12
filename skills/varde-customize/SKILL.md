---
name: varde-customize
description: "Author or tune code scan rules and Toz output profiles or custom filters. Not for installing or configuring Varde (varde-manage) or triaging scan findings (varde-scan)."
recommends: [varde-change, varde-code]
---

# Customize scans and output

Before editing repository files (scan rules or project profiles), load
`varde-change`: use your skill tool, or read `../varde-change/SKILL.md`; it
owns the review gate.

## Choose the task

| The request is | Read |
|---|---|
| Add a code scan rule or tune its matches, severity, or thresholds | `references/scan-author.md` |
| Customize tool-output previews, sections, or extracted records | `references/toz-profiles.md` |

For an ambiguous “custom filter,” establish whether it means code findings,
output presentation, redaction, or excluding captures, then select the row.

## Gotchas

- `varde-customize` is a harness skill, not a shell executable.
- Inspect existing configuration and loaded provenance before replacing an
  entry. Preserve unrelated settings; prefer a scoped override to a new tool.
- Report what changed, which fixtures ran, and whether the intended configuration
  actually loaded. A successful command alone does not establish activation.

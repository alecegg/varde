---
name: varde-customize
description: "Use this skill when the user wants to add or tune a code scan rule, or customize Toz output profiles, previews, sections, extracted records, or custom filters."
recommends: [varde-build, varde-code, varde-toz]
---

# Customize scans and output

- Edits to repository files (scan rules or project profiles) go through the
  build review gate.

## Choose the task

| The request is | Read |
|---|---|
| Add a code scan rule or tune its matches, severity, or thresholds | `references/scan-author.md` |
| Customize tool-output previews, sections, or extracted records | `references/toz-profiles.md` |

An ambiguous "custom filter" is settled first as one of:

- code findings
- output presentation
- redaction
- excluding captures

## Gotchas

- `varde-customize` is a harness skill, not a shell executable.
- Existing entries are inspected before replacement; unrelated settings are
  preserved; a scoped override is preferred to a new tool.
- Report what changed, which fixtures ran, and whether the intended configuration
  actually loaded. A successful command alone does not establish activation.

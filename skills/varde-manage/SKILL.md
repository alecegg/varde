---
name: varde-manage
description: "Install, upgrade, or configure Varde skills, CLIs, and harness hooks; create or tune code scan rules and Toz output profiles or custom filters. Not for triaging scan findings, querying captures, or changing application code."
---

# Manage Varde setup and customization

Before implementation edits, route the change through `varde-change` and apply
`references/review-gates.md`. Carry its verdict through completion.

## Choose the task

| The request is | Read |
|---|---|
| Install, update, repair wiring, or configure paths and capture settings | `references/setup.md` |
| Add a code scan rule or tune its matches, severity, or thresholds | `references/scan-author.md` |
| Customize tool-output previews, sections, or extracted records | `references/toz-profiles.md` |

For an ambiguous “custom filter,” establish whether it means code findings,
output presentation, redaction, or excluding captures, then select the row.

## Gotchas

- `varde-manage` is a harness skill, not a shell executable. The setup script
  lives in a Varde checkout; discover it before invoking it.
- Inspect existing configuration and loaded provenance before replacing an
  entry. Preserve unrelated settings; prefer a scoped override to a new tool.
- Report what changed, which fixtures ran, and whether the intended configuration
  actually loaded. A successful command alone does not establish activation.

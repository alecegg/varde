---
type: decision
description: Defines the shared versioned machine-output envelope across Varde CLIs.
generated: { by: codex/gpt-5, at: 2026-09-22T22:11:32Z }
paths:
  - clis/code/crates/varde-code/src/query/mod.rs
  - clis/workflow/varde-workflow/src/output.rs
---

## What

Machine output uses `schema_version`, `ok`, `outcome`, `data`, and `meta`.
Typed failures live under `data.error`.

## Why

One envelope lets integrations handle every Varde CLI uniformly.

## Constraints

- Large collections default to bounded, recoverable pages.
- `meta.truncated` reports omitted results.
- Pagination metadata provides offsets and full-result recovery controls.

## Related

- [Workflow artifact kernel](/reference/workflow-artifact-kernel.md)

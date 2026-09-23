---
type: reference
description: Defines Varde's versioned workflow artifact mechanics.
generated: { by: codex/gpt-5, at: 2026-09-19T02:30:00Z }
paths:
  - workflow-cli/varde-workflow/src/artifact.rs
  - workflow-cli/varde-workflow/src/migration.rs
  - workflow-cli/varde-workflow/src/journal.rs
---

# Workflow artifact kernel

`varde-workflow` owns mechanical workflow artifact operations.
Skills retain policy judgment and qualitative decisions.

## Envelope

Schema version `1` requires artifact type, identifier, relationships,
and provenance. Status remains optional across artifact types.
The content revision derives from exact source bytes.

Legacy Markdown receives a deterministic read-only envelope.
Its derived identifier uses the source content revision.
Legacy inspection never changes the underlying source bytes.

## Direct edits

Direct Markdown editing remains supported for versioned artifacts.
Valid edits produce a new revision during inspection.
Invalid edits return field diagnostics and preserve bytes.
No command repairs malformed content silently.

## Migration and recovery

Legacy mutations require an explicit migration preview first.
`migrate --apply` authorizes exactly that structural rewrite.
Staged writes record paths, hashes, phases, and actions.
`recover` commits matching staged bytes exactly once.

Recovery uses advisory locking around journal processing.
It never claims atomicity across the complete filesystem.

## Output and availability

Machine output uses one versioned JSON response envelope.
Success payloads appear under `data`. Failures use `error`.
Human output remains separate from machine-readable output.

Mutations require the CLI and stop when unavailable.
Read-only workflows may use an explicitly degraded fallback.

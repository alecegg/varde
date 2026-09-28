---
type: reference
description: Defines Varde's versioned workflow artifact mechanics.
generated: { by: codex/gpt-5, at: 2026-09-19T02:30:00Z }
paths:
  - clis/workflow/varde-workflow/src/artifact.rs
  - clis/workflow/varde-workflow/src/journal.rs
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

## Review evidence

`review init` binds a subject to a canonical repository, persisted plan or
bounded contract, and immutable scoped baseline. Reviewer-authored approval
records and baseline blobs live in the configured working store. `inspect`,
`record`, and `check` use inspected revisions so changed contracts, coverage,
or source evidence cannot be silently accepted. The coordinator cannot supply
an approval flag.

Workflow start, resume, and completion checkpoints consume this evidence.
Planning readiness remains distinct from implementation readiness. Missing or
stale evidence blocks gated implementation and completion; it does not prevent
planning or rewriting a contract for renewed review. Review commands are
required for gated work and do not have a manual fallback.

## Explicit worktree authority

Subjects keep exact repository identity. An explicitly registered linked
worktree may reuse a current parent pre-edit approval for its bounded owned
scope. Its registration pins Git path/branch/common-directory identity, starting
commit, parent approval and optional task contract; worker baselines and change
evidence remain separate. Start/resume checks require explicit binding context.
Workers cannot record parent approvals or conclude parents through that context.

The approval checkout owns isolated task state writes after verified source
integration. Release verifies the integrated commit and archives worker evidence
before cleanup. Live bindings block parent completion; archived binding evidence
participates in its combined change fingerprint and independent final review.

Stale approval cannot authorize execution. Read-only inspection retains current
evidence/version; current approved active parents may archive valid integrated
source within current scope. Explicit abandonment archives available evidence
(or unavailable status), preserves source/branch/checkout, and cannot complete
a task. Both terminal archives require current combined final review.

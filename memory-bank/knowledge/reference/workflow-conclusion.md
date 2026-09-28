---
type: reference
status: stable
---

# Workflow conclusion

Contracts prescribe intended behavior.
Observed specifications describe current source behavior.
Conclusion keeps both artifact classes independent.

Plans declare relative artifact paths through these fields:

- `contract_deltas`
- `promotion_candidates`
- `observed_specs`

Contract deltas use schema version `1`.
They contain `ADDED`, `MODIFIED`, and `REMOVED` sections.
Existing contract changes require the current base revision.

Observed specifications must match every recorded source hash.
They must also match their deterministic aggregate source hash.
Semantic regeneration remains owned by `varde-docs spec`.

Promotion candidates require accepted status and provenance.
Required fields include source plan and source review.
Disposition, staleness, and resolution remain searchable afterward.

Conclusion validates dependency and review prerequisites before staging writes.
When review is required, current independent implementation evidence must cover
the complete subject change. A missing or stale record rejects before
promotions or plan status are written.
It then journals contracts, promotions, records, and plan status.
The journal retains consumed review and source revisions. Recovery validates
untouched prerequisites and finishes staged or partially committed writes
exactly once; changed prerequisites remain a conflict for diagnosis.

Reflection, friction, and handoff follow mechanical conclusion.
Their state remains visible and independently retryable.
Action outputs deduplicate during idempotent status recording.

Group plans retain aggregate scope, child dependency/contract evidence and
acceptance criteria. Their own independent pre-edit and combined implementation
reviews augment child gates; active groups resume without repeated activation.
All child completion and aggregate checks precede group conclusion. Active
worktree bindings block parent completion. Separate archived worker evidence
and integrated source contribute to the current aggregate fingerprint.

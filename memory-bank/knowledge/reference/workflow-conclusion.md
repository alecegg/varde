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

Conclusion validates every prerequisite before staging writes.
It then journals contracts, promotions, records, and plan status.
Recovery finishes staged or partially committed writes exactly once.

Reflection, friction, and handoff follow mechanical conclusion.
Their state remains visible and independently retryable.
Action outputs deduplicate during idempotent status recording.

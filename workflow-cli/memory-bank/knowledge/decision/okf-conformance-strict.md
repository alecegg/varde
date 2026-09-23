---
id: decision/okf-conformance-strict
type: decision
status: accepted
generated:
  by: human:unspecified
  at: 2026-08-13T20:30:18.098Z
verified: []
paths: []
enriched_at_commit: null
_version: f8dcc2ca18357a69f0f3e83b8c9d4bf8c94420ca3d2c9d3ad3d4813f4917677f
---

## What

varde-workflow implements OKF v0.2 strictly as spec'd at
https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf
(SPEC.md). No cyano-specific frontmatter extensions (e.g. cyano's
`paths`, `enriched_at_commit` fields) are added by default.

## Why

Bundles this tool produces should be portable to any OKF consumer, not
just cyano — fits the "standalone, not an extraction of cyano" framing.
Extensions can be layered on additively later without breaking strict
conformance, but starting strict is easier than retrofitting portability
after cyano-specific fields have crept in.

## Constraints

- Revisit if a concrete feature (e.g. contradiction lint, vault layering)
  turns out to need a field the spec doesn't provide — prefer proposing
  it as a `sources`/tags-based encoding within the spec first, and only
  add a true extension field if that's not workable.

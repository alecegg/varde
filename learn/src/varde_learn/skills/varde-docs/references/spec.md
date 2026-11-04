# Regenerate domain specifications

Generate one reviewable specification per domain, plus architecture and index
documents. Ground every spec only in source read directly in this run, within
the domain's boundary.

## Outcomes

- Domains needing updates are found per Find domains below; spec documents
  follow `references/spec-format.md`. A domain is one workspace member/package,
  else one top-level source directory with its own entry point; on a first run
  (no `index.md`) state the list.
- Domains are generated one at a time by default; delegate only domains with
  independent source and output paths, to at most three active builders.
- Use `varde map context_pack` (see `references/varde-code-cli.md`) to map
  domains to source.
- Architecture is never inferred from folder layout alone. A scoped run still
  refreshes a stale architecture document (only an explicit user ban leaves it
  stale, and that is reported).
- Delete each domain document in the flat specs root (`specs/<slug>` maps to
  `<knowledge>/specs/<slug>.md`) whose code you have confirmed no longer
  exists. Never delete the architecture document.
- The index is rendered after domain generation, per `references/spec-format.md`.

## Verify

Compare each generated spec with the source it describes:

- writes stay under `<knowledge>/specs/`;
- spot-check operations, types, and invariants, and mark unverified areas
  degraded;
- recompute provenance; a mismatch means regenerate once, then report any remaining mismatch;
- links resolve;
- with `varde` on PATH, run `varde learn memory lint` and report findings; lint does not block;
- once changed specifications pass, refresh the verified inventory with
  `varde learn docs spec --repository <repo-root> --knowledge <knowledge> --working <working> --refresh --json`, and
  report a refresh failure rather than claim a cache hit.

## Report

The Domain/Written/Failed/Skipped table, then:

- the architecture decision (written or unchanged) and any extra write
- orphans
- overlapping and unmatched/unclassified paths
- broken links
- drift
- degraded checks

## Find domains needing updates

| Status | Condition |
|---|---|
| missing | No document. |
| stale | `source_roots` or `covered_paths` is missing (legacy), or a fresh recompute changes any entry hash, the aggregate, or the covered-path inventory. |
| `reuse` (up to date) | Otherwise; skip unless the user asked to force-regenerate. |

The status source is `varde learn docs spec --repository <repo-root> --knowledge <knowledge> --working <working> --json`. If it is unavailable or fails, stop spec mode and report it.
Unmatched, overlapping, and unclassified paths are reported on every run, including scoped runs.

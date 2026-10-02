# Regenerate domain specifications

Generate one reviewable specification per domain, plus architecture and index
documents. Ground every spec only in source read directly in this run, within
the domain's boundary.

## Workflow

1. **Find domains needing updates** per Find domains below.
2. **Generate domain documents** per `references/spec-format.md`, one at a
   time by default. With `varde-code` on PATH, load
   `references/varde-code-cli.md`, and batch discovery and relationship queries
   per domain; use `get_symbol`/`batch` for exact bodies and related lookups.
3. **Check the architecture document** per Architecture below.
4. **Delete orphans:** each domain document in the flat specs root
   (`specs/<slug>` maps to `<knowledge>/specs/<slug>.md`) whose code you have
   confirmed no longer exists, never the architecture document.
5. **Render the index** after domain generation, per
   `references/spec-format.md`.
6. **Verify.** Compare each generated spec with the source it describes:
   - writes stay under `<knowledge>/specs/`;
   - spot-check operations, types, and invariants, and mark unverified areas
     degraded;
   - recompute provenance; a mismatch means regenerate once, then report any remaining mismatch;
   - links resolve;
   - with `varde-workflow` on PATH, run `varde-workflow lint --bundle
     <knowledge>` and report findings; lint does not block;
   - once changed specifications pass, refresh the verified inventory with
     `varde-workflow spec inventory --repository <repo-root> --knowledge
     <knowledge> --working <working> --refresh --json` when available, and
     report a refresh failure rather than claim a cache hit.
7. **Report the summary:** the Domain/Written/Failed/Skipped table, then:
   - the architecture decision and any extra write
   - orphans
   - overlapping and unmatched/unclassified paths
   - broken links
   - drift
   - degraded checks
8. **Record lessons:** real obstacles through `varde-learn`; skip otherwise.

### Delegating domains

Delegate only domains with independent source and output paths, to at most
three active executors that each write one document under
`<knowledge>/specs/`. Brief each with:

- Resolved absolute `<working>` and `<knowledge>` paths, used without
  re-resolving.
- The `varde-code` path, if on PATH.
- Domain, changed files, output path, and `spec-format.md`.

## Find domains needing updates

| Status | Condition |
|---|---|
| missing | No document. |
| stale | `source_roots` or `covered_paths` is missing (legacy), or a fresh recompute changes any entry hash, the aggregate, or the covered-path inventory. |
| `reuse` (up to date) | Otherwise; skip unless the user asked to force-regenerate. |

1. Run `varde-workflow spec inventory --repository <repo-root> --knowledge
   <knowledge> --working <working> --json` and reuse its per-domain statuses
   and its `overlapping`, `unmatched`, and `unclassified_paths` inventory. If it is
   unavailable or fails, stop spec mode and report it.
2. Group the inventory's `missing` source directories into domains: one per
   workspace member/package, else one per top-level source directory with its
   own entry point. On a first run (no `index.md`), state the list.
3. Settle architecture and path classification per the sections below.

No missing or stale domain skips only workflow step 2; continue with steps
3-8.

### Architecture

- If no sources are found, skip and say so. Never infer architecture from
  folder layout alone.
- Otherwise, leave the document byte-identical unless it needs a refresh.

Architecture sources are the files declaring deployed units, their wiring, and
package/workspace structure (infrastructure-as-code, deployment config,
workspace manifests), including new declaration files outside old roots, plus
every entrypoint or handler read to map units to domains. Recompute their
provenance and covered paths like a domain's.

Refresh architecture only when it is missing or stale, its declaration set
changed, or a domain was added or removed.
Write `<knowledge>/specs/architecture.md` with `domain: architecture` per
`references/spec-format.md`, and list it in the index.

| Inventory `architecture_status` | Action |
|---|---|
| `none` | Inspect `architecture_candidates` first; a candidate can be a deployment or workspace declaration the inventory cannot identify by filename. |
| `inspect` | Read each `architecture_inspect_paths` entry. Refresh architecture if it affects deployed units or wiring; otherwise acknowledge it with `varde-workflow spec inventory --repository <repo-root> --knowledge <knowledge> --working <working> --acknowledge-architecture-path <path> --json` (repeatable; binds the current content hash and expires when that content changes). |

### Unclassified and overlapping paths

Report these on every run, including scoped runs:

- current source candidates (workspace members, source directories,
  entrypoints, deployment declarations) outside all domain `source_roots`;
- candidates covered by more than one domain root;
- architecture overlap with domains, without changing a domain boundary.

Inspect each `unclassified_paths` entry before classifying it as a new domain
source, an architecture declaration, or unrelated; an unrecognized extension
does not make it unrelated.

## Scoped runs

Given specific domains (e.g. plan `observed_specs`):

- Regenerate only those domain documents; skip full domain discovery and
  workflow step 4.
- Still read other domain roots for overlap and `unclassified_paths`
  classification.
- Still refresh a stale architecture document; "only <domain>" limits domain
  documents. Only an explicit user ban on architecture edits leaves it stale;
  report that.
- Report whether architecture was written or left unchanged.

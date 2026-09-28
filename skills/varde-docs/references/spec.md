# Regenerate domain specifications

Generate one reviewable specification per domain, plus architecture and index
documents. Read the code directly — every spec is grounded only in source you
read in this run, within the domain's boundary.

## Workflow

Given specific domains (e.g. plan `observed_specs`): regenerate only those,
skip full domain discovery and step 4 (no orphan deletion). Still inspect
architecture provenance and covered paths, then refresh it only when affected.
Report whether architecture was written or left unchanged.
"Only <domain>" limits domain documents; the shared architecture document
is an additional output when stale. If the user explicitly forbids an
architecture edit, leave it unchanged and report the stale state.
Read other domain roots for overlap and `unclassified_paths` classification without
regenerating their documents.

1. **Find domains needing updates.** Full procedure: `references/spec-plan.md`.
2. **Generate domain documents.** Load `references/spec-format.md`. Generate
   domains one at a time by default. Delegate only domains with independent
   source and output paths, with at most three delegates active. Each
   executor writes exactly one document under `<knowledge>/specs/`. With
   `varde-code` on PATH, also load `references/varde-code.md` and batch
   discovery and relationship queries across its domain. Brief each delegate
   with resolved absolute `<working>` and `<knowledge>` paths (used without
   re-resolving), the `varde-code` path (if on PATH), domain, changed files,
   output path, and `spec-format.md`.
3. **Check and, when affected, generate the architecture document.** Identify the files that declare
   deployed units, their wiring, and package/workspace structure, such as
   infrastructure-as-code, deployment config, and workspace manifests. Hash
   these as `sources`. Read the entrypoint or handler code they reference to
   map units to domains, and include every entrypoint or handler used for that
   mapping in `sources` too. None found → skip and say so; never infer
   architecture from folder layout alone. On a scoped run, compare the
   architecture spec's source hashes and covered paths with current files.
   Rediscover deployment and workspace declarations so a new declaration
   outside the old roots also counts as affected; check whether a domain was
   added or removed. Leave an up-to-date
   architecture document byte-identical. On a full run, use the same
   affected check from `references/spec-plan.md`. When affected, write
   `<knowledge>/specs/architecture.md` with `domain: architecture`, format
   per `references/spec-format.md`; list it in the index; exempt it from
   orphan deletion.
4. **Delete orphans.** Delete every domain document whose corresponding code
   no longer exists, from the flat specs root (`specs/<slug>` maps to
   `<knowledge>/specs/<slug>.md`). Deletion is confined to `specs/`,
   to documents you have confirmed are orphans, and never to the architecture
   document.
5. **Render the index** after domain generation finishes. Format:
   `references/spec-format.md`. Write it only when bytes differ.
6. **Verify.** Compare each generated spec with the source it describes:
   - writes stay under `<knowledge>/specs/`
   - spot-check operations, types, and invariants, and mark unverified areas
     degraded
   - recompute provenance; a mismatch means regenerate
   - links resolve
   - If `varde-workflow` is on PATH, run `varde-workflow lint --bundle
     <knowledge>` and report findings; lint does not block.
   - After changed specifications pass these checks, refresh the verified
     inventory with `varde-workflow spec inventory --repository <repo-root>
     --knowledge <knowledge> --working <working> --refresh --json` when the
     command is available. Report a refresh failure; do not claim a cache hit.
7. **Report the summary.** Output: the Domain/Written/Failed/Skipped table,
   then the architecture decision and any extra write, orphans, overlapping
   and unmatched/unclassified paths, broken links, drift, and degraded checks.
8. **Record lessons.** Record real obstacles through `varde-learn` and durable
   decisions through `varde-knowledge`.

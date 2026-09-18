# Refresh user-facing documentation

Keep user-facing documentation accurate for the current codebase and generated
specifications.

This skill has two kinds of output:

- **Auto-generate**: sections explicitly declared inside a freshness marker are
  rewritten by reading the source they describe and authoring the replacement text
  directly.
- **Propose**: all other content — hand-authored sections in marked docs, and the
  entirety of unmarked docs — is compared against the current code/specs and
  surfaced as a proposed diff for user review. Changes are applied only on approval.

## Inputs

- `repoRoot`: absolute repository path.
- `docPath`: README.md or a direct docs/*.md path being regenerated.

## Workflow

1. **Choose the working location.** Work in the current checkout by default.
   This skill is interactive — Phase 3 proposes edits for the user to approve —
   so the user must be able to see the docs being changed in their own checkout;
   a worktree would hide them. Isolate per `references/worktree.md` (id
   `docs-<short-id>`, running every step below with the printed `path=` as the
   effective `repoRoot`) **only** when a concrete concurrent-edit risk makes the
   local checkout unsafe — another agent editing the same docs mid-run. If you
   do isolate, merge back before Phase 3's approval step so the user reviews the
   real files, and follow that file's `created=` ownership rule. Interactive-throughout work belongs in the checkout,
   not a worktree.
2. **Load the optional CLIs.** Load `references/varde-code.md` if that CLI is
   on PATH — it is the preferred way to scope Phase 1 and read source content
   in Phases 0 and 2. Likewise load `references/varde-docs-cli.md` if
   `varde-docs` is; when present,
   use it to read generated specs and for ranked `search`/whole-doc `show` and
   OCC-safe whole-file writes over README/`docs/*.md` — section-marker
   rewrites stay Edit. Absent, use plain Read/Grep/Write/Edit.
3. **Refresh specifications first, if any exist.** Check whether the repo has
   generated specification documents (e.g. under `memory-bank/knowledge/specs/`
   or similar). If so, update any that are stale before touching docs. Full
   procedure: `references/refresh-phase-0-spec.md`.
4. **Discover all documents.** Enumerate README.md and docs/*.md, classify
   each as marked or unmarked. For marked docs, resolve each marker's
   `source_hash` against the matching local generated spec's provenance to
   find which declared sections actually changed. Full procedure:
   `references/refresh-phase-1-discovery.md`.
5. **Auto-generate spec-declared sections.** Process stale documents one at a
   time. Delegate only independent documents when their source and output paths
   cannot overlap; cap concurrent delegates at three. Full procedure:
   `references/refresh-phase-2-autogenerate.md`.
6. **Propose edits for all docs.** Process documents one at a time. Delegate
   only independent comparisons and cap concurrent delegates at three. Full
   procedure: `references/refresh-phase-3-propose.md`.
7. **Verify generated documents.** Re-read each edited document next to the
   source it describes and check for accuracy and drift; report findings without
   auto-repairing them. Full procedure: `references/refresh-phase-4-verify.md`.
8. **Merge back only if you isolated.** In the default current-checkout case
   there is nothing to merge — skip this step. You only reach here with an open
   worktree if step 1 isolated for a concurrent-edit risk *and* the run never
   reached Phase 3's approval; in that case merge and clean up per
   `references/worktree.md`, whose `created=` rule decides ownership. On a merge
   conflict, resolve with
   intent "regenerate docs from current source/specs" before cleaning up.
9. **Record lessons.** Invoke `varde-knowledge reflect`, scoped to this run. It
   records friction and durable lessons only — a handoff belongs at a
   session boundary, which this is not.

## Constraints

- Write only prose grounded in the source it describes.
- Scope is `README.md` and `docs/*.md`. CHANGELOGs, release notes, and external
  doc sites have their own owners.
- Use Mermaid only for diagrams.

## Gotchas

- `references/refresh-marker-format.md` defines the source-to-document mapping. A bad
  marker can silently break Phase 2 rewrites and Phase 3 marker proposals.
- Phase 2 only rewrites marker-declared blocks; it never touches
  hand-authored content, even in a marked doc — that content only ever moves
  through Phase 3's propose-and-approve path.
- Phase 4 verification only reports malformed markers, missing source
  references, and unbalanced Mermaid fences — it does not repair them; fixes
  go back through Phase 2/3, not through an automated Phase 4 fix.

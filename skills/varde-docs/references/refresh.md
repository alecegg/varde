# Refresh user-facing documentation

Keep user-facing documentation accurate for the current codebase and generated
specifications.

This skill has two kinds of output:

- **Auto-generate**: Rewrite sections declared inside a freshness marker by
  reading the source they describe and authoring replacement text directly.
- **Propose**: Compare all other content — hand-authored sections in marked docs
  and all content in unmarked docs — with the current code/specs. Show the
  differences for user review. Apply changes only after approval.

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
   real files, and follow that file's `created=` ownership rule. Keep all
   interactive work in the checkout, not a worktree.
2. **Load optional CLIs.** Load `references/varde-code.md` for unknown scope,
   changed relationships, or several related lookups. Read one short, known
   source file directly. Load `references/varde-workflow-cli.md` only for
   ranked bundle search or whole-file mutation. Read known documents directly
   when no mutation follows. Section-marker rewrites stay Edit.
3. **Refresh specifications first, if any exist.** Check whether the repo has
   generated specification documents (e.g. under `<knowledge>/specs/`
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
7. **Verify generated documents.** Compare each edited document with the source
   it describes. Check accuracy and drift, then report findings without
   repairing them automatically. Full procedure:
   `references/refresh-phase-4-verify.md`.
8. **Merge back only if you isolated.** If you stayed in the current checkout,
   skip this step. You reach this step with an open worktree only when step 1
   isolated for a concurrent-edit risk and the run stopped before Phase 3's
   approval. In that case, merge and clean up per
   `references/worktree.md`, whose `created=` rule decides ownership. On a merge
   conflict, resolve with
   intent "regenerate docs from current source/specs" before cleaning up.
9. **Record lessons.** Invoke `varde-knowledge reflect`, scoped to this run. It
   records friction and durable lessons. Do not write a handoff during this run.

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

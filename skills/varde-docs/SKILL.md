---
name: varde-docs
description: >
  TRIGGER: Refresh user-facing README.md and docs/*.md files. Scan all docs,
  regenerate spec-declared sections, and propose edits for hand-authored sections.
  SKIP: Skip only when the request concerns code, plans, or generated specs alone.
  Example phrases: "refresh the README" or "check docs for drift".
---

## Purpose

Keep all user-facing documentation aligned with the current state of the codebase
(and any generated specifications, if the project has them).

The varde-docs skill has two output tracks:

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
   a worktree would hide them. Isolate via the `varde-worktree` skill (`create
   id=docs-<short-id>`, run every step below with the printed `path=` as the
   effective `repoRoot`) **only** when a concrete concurrent-edit risk makes the
   local checkout unsafe (another agent editing the same docs mid-run). If you
   do isolate, you must `merge` back before Phase 3's approval step so the user
   reviews the real files, and follow `varde-worktree`'s `created=` ownership
   rule for merge/cleanup. Interactive-throughout work belongs in the checkout,
   not a worktree.
2. **Check for the `varde-code` CLI.** Check once per session whether the
   `varde-code` CLI (an optional tool, installed on PATH) is available: run
   `command -v varde-code >/dev/null 2>&1`. If present, load
   `references/VARDE-CODE-CLI.md`: it's the
   primary way to scope Phase 1's diff and to read source content in
   Phases 0 and 2, instead of Read/Grep. If it isn't, ignore that file and
   use the plain Read/Grep workflow in every phase below. Likewise, if
   `command -v varde-docs >/dev/null 2>&1` succeeds, load `references/VARDE-DOCS-CLI.md`; when present,
   use it to read generated specs and for ranked `search`/whole-doc `show` and
   OCC-safe whole-file writes over README/`docs/*.md` — section-marker
   rewrites stay Edit. Absent, use plain Read/Grep/Write/Edit.
3. **Refresh specifications first, if any exist.** Check whether the repo has
   generated specification documents (e.g. under `memory-bank/knowledge/specs/`
   or similar). If so, update any that are stale before touching docs. Full
   procedure: `references/PHASE-0-SPEC-REFRESH.md`.
4. **Discover all documents.** Enumerate README.md and docs/*.md, classify
   each as marked or unmarked. For marked docs, use `detect_changes` against
   each marker's `source_hash` to find which declared sections actually
   changed, instead of reading every doc/source pair. Full procedure:
   `references/PHASE-1-DISCOVERY.md`.
5. **Auto-generate spec-declared sections.** Process stale documents one at a
   time. Delegate only independent documents when their source and output paths
   cannot overlap; cap concurrent delegates at three. Full procedure:
   `references/PHASE-2-AUTOGENERATE.md`.
6. **Propose edits for all docs.** Process documents one at a time. Delegate
   only independent comparisons and cap concurrent delegates at three. Full
   procedure: `references/PHASE-3-PROPOSE.md`.
7. **Verify generated documents.** Re-read each edited document next to the
   source it describes and check for accuracy and drift; report findings without
   auto-repairing them. Full procedure: `references/PHASE-4-VERIFY.md`.
8. **Merge back only if you isolated.** In the default current-checkout case
   there is nothing to merge — skip this step. You only reach here with an open
   worktree if step 1 isolated for a concurrent-edit risk *and* the run never
   reached Phase 3's approval; in that case, when `create` returned
   `created=true`, run `merge id=docs-<short-id>` then `cleanup id=docs-<short-id>`
   (if `created=false`, the owner handles it). On a merge conflict, follow
   `varde-worktree`'s `references/RESOLVE.md` with intent "regenerate docs from
   current source/specs" before cleaning up.
9. **Reflect and consolidate.** Invoke `varde-reflect source=varde-docs` — it
   captures friction scoped to this skill's own execution and harvests any durable
   knowledge the work produced (no handoff mid-session). If `varde-reflect` isn't
   installed, fall back to `varde-friction` with the same scope.

## Constraints

- Write only prose grounded in the source it describes — do not invent details.
- Do not create CHANGELOG, release-note, or external doc-site output.
- Use Mermaid only for diagrams.

## Gotchas

- The freshness marker format (`references/MARKER-FORMAT.md`) is the single
  source of truth for the source-to-document mapping — both Phase 2 (rewriting
  marker-declared blocks) and Phase 3 (proposing a marker for unmarked docs)
  depend on it, so a malformed marker breaks both tracks silently.
- Phase 2 only rewrites marker-declared blocks; it never touches
  hand-authored content, even in a marked doc — that content only ever moves
  through Phase 3's propose-and-approve path.
- Phase 4 verification only reports malformed markers, missing source
  references, and unbalanced Mermaid fences — it does not repair them; fixes
  go back through Phase 2/3, not through an automated Phase 4 fix.

---
name: varde-spec
description: >
  TRIGGER: Regenerate domain-first specification documents after code changes
  by reading the current source.
  SKIP: Skip only when the user wants user-facing docs, a code review, or code
  implementation without generated specifications.
  Example phrases: "regenerate the specs" or "update domain specifications".
---

Generate reviewable specification documents from the current source code: one
document per domain, plus architecture and index documents. Generated
documents are committed and derived by directly reading the code they
describe, not by any automated generation service.

## Workflow

1. **Isolate the run.** This skill reads across the whole codebase before
   writing anything, then may delegate bounded domain work during a long run —
   a concurrent code edit landing mid-run (by another agent or
   the user) could produce a spec describing code that no longer matches.
   Always isolate via the `varde-worktree` skill: `create id=spec-<short-id>`, run
   every step below with the printed `path=` as the effective `repoRoot` —
   this protects the whole run from mid-run edits, not just a dirty start,
   so it applies on a clean tree too, not only when `git status --porcelain`
   in `repoRoot` is non-empty. You don't check whether you're already nested:
   `create` returns `created=false` and reuses a caller's worktree on its own
   (see `varde-worktree`'s ownership rule). Also, once per session, if
   `command -v varde-docs >/dev/null 2>&1` succeeds, load `references/VARDE-DOCS-CLI.md`; when
   present, write/refresh/delete spec concepts and lint through it (same files
   under `memory-bank/knowledge/specs/`), otherwise use plain Write/Edit/`git
   rm`.
2. **Plan the dirty domains.** Check once per session whether the
   `varde-code` CLI (an optional tool, installed on PATH) is available: run `command -v varde-code >/dev/null 2>&1`.
   If present, load `references/VARDE-CODE-CLI.md` and use it as the primary way to
   scope this step: diff against the `source_commit` recorded in the prior
   run's `index.md` (via `detect_changes`) instead of scanning the whole
   repo, and load that file for the dependency-graph operations that also
   feed step 3. If it isn't, ignore that file and compare existing spec
   documents against the current code structure by reading both. Full
   procedure: `references/SPEC-PLAN.md`.
3. **Generate domain documents.** Generate domains one at a time by default.
   Delegate only domains with independent source and output paths, with at most
   three delegates active. Each executor writes exactly one document under
   `memory-bank/knowledge/specs/`. When `varde-code` was detected in step 2,
   each executor reads its domain's code primarily via CLI symbol queries
   (`symbols_in_files`/`get_symbol` with `includeBody`), falling back to
   Read only for what the CLI can't supply. A delegated executor receives the
   binary path and domain changed-file list. Otherwise the executor reads
   source files directly. Format and generation contract:
   `references/SPEC-FORMAT.md`.
4. **Delete orphans.** Delete every domain document whose corresponding code
   no longer exists, from the flat specs root (`specs/<slug>` maps to
   `memory-bank/knowledge/specs/<slug>.md`); never delete a document you are
   not certain is an orphan, and never delete files outside `specs/`.
5. **Write the index.** After domain generation finishes, write
   `memory-bank/knowledge/specs/index.md` deterministically. Index format:
   `references/SPEC-FORMAT.md`.
6. **Verify.** Read each generated spec next to the source it describes and
   check for accuracy and drift manually; report broken links and orphan
   files. Conditions checked: `references/VERIFY-AND-REPORT.md`.
7. **Report the summary.** Domain write/fail/skip counts, deleted orphan
   domains, ambiguous domains retained, broken links, write failures, and
   drift findings. Output format: `references/VERIFY-AND-REPORT.md`.
8. **Merge the isolated run back.** Only when step 1's `create` returned
   `created=true` do you own the worktree: invoke `merge id=spec-<short-id>`
   then `cleanup id=spec-<short-id>` from the `varde-worktree` skill. If it
   returned `created=false` (nested in a caller's worktree), skip merge and
   cleanup — the owner does that. On a merge conflict, follow that skill's
   `references/RESOLVE.md` with intent "regenerate domain specs from current
   source" before cleaning up.
9. **Reflect and consolidate.** Invoke `varde-reflect source=varde-spec` — it
   captures friction scoped to this skill's own execution and harvests any durable
   knowledge the work produced (no handoff mid-session). If `varde-reflect` isn't
   installed, fall back to `varde-friction` with the same scope.

## Gotchas

- Never delete a domain document you are not confident is an orphan — when
  unverifiable, leave it in place rather than risk data loss.
- `index.md` must carry no frontmatter — it is a directory listing, not a
  domain document.
- Do not recreate legacy `views/` directories — the flat `specs/` layout
  replaced them.
- When editing an existing domain document, preserve hand-authored sections
  and apply targeted edits only to sections that changed.
- On the first run, when `specs/index.md` is absent, wipe only the contents
  of `memory-bank/knowledge/specs/` before generation (preserve the directory
  itself) — this is the one-time clean transition from the retired view
  layout.

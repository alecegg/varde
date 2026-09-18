# Regenerate domain specifications

Generate one reviewable specification per domain, plus architecture and index
documents. Files under `memory-bank/` are local and can be regenerated. Read the
code directly — every spec is grounded in source you actually read.

## Workflow

1. **Choose where to work.** Run
   `git check-ignore -q memory-bank/knowledge/specs/.varde-spec-probe` before
   creating a worktree. When it exits `0`, run in the caller checkout so
   existing ignored specifications and Notes remain visible, and so generated
   artifacts stay there. When it exits `1`, isolate per `references/worktree.md`
   using id `spec-<short-id>`, then use its printed `path=` as the effective
   `repoRoot`. This protects tracked specification runs from concurrent source
   edits and preserves normal Git merging. You need not check whether you are
   already nested — creation reuses a caller's worktree on its own.
   State the detected storage mode before continuing. Load
   `references/varde-docs-cli.md` if `varde-docs` is on PATH; when present, write/refresh/delete spec concepts and lint through it (same files
   under `memory-bank/knowledge/specs/`), otherwise use plain Write/Edit/`git
   rm`.
2. **Find domains needing updates.** Load `references/varde-code.md` if that
   CLI is on PATH and make it the primary way to scope this step: diff against
   the `source_commit` recorded in the prior run's `index.md` (via
   `detect_changes`) rather than scanning the whole repo. Without it, compare
   existing spec documents against the current code structure by reading both.
   Full procedure: `references/spec-plan.md`.
3. **Generate domain documents.** Generate domains one at a time by default.
   Delegate only domains with independent source and output paths, with at most
   three delegates active. Each executor writes exactly one document under
   `memory-bank/knowledge/specs/`. When `varde-code` was detected in step 2,
   each executor reads its domain's code primarily via CLI symbol queries
   (`symbols_in_files`/`get_symbol` with `includeBody`), falling back to
   Read only for what the CLI can't supply. A delegated executor receives the
   binary path and domain changed-file list. Otherwise the executor reads
   source files directly. Before editing any document, load and follow
   `references/spec-format.md` completely. It owns provenance, generated-block
   boundaries, Notes preservation, legacy migration, meaning-layer rendering,
   and the per-agent contract. Generated specifications under ignored
   `memory-bank/` storage stay local artifacts, out of any commit.
4. **Delete orphans.** Delete every domain document whose corresponding code
   no longer exists, from the flat specs root (`specs/<slug>` maps to
   `memory-bank/knowledge/specs/<slug>.md`). Deletion is confined to `specs/`,
   and to documents you have confirmed are orphans.
5. **Write the index.** After domain generation finishes, write
   `memory-bank/knowledge/specs/index.md` deterministically. Index format:
   `references/spec-format.md`.
6. **Verify.** Read each generated spec next to the source it describes and
   check for accuracy and drift manually; report broken links and orphan
   files. Conditions checked: `references/spec-verify.md`.
7. **Report the summary.** Domain write/fail/skip counts, deleted orphan
   domains, ambiguous domains retained, broken links, write failures, and
   drift findings. Output format: `references/spec-verify.md`.
8. **Merge tracked output back.** Only if step 1 created a worktree you own:
   merge then clean up per `references/worktree.md`, whose `created=` rule
   decides. On a merge conflict, resolve with intent
   "regenerate domain specs from current source" before cleaning up.
9. **Record lessons.** Invoke `varde-knowledge reflect`, scoped to this run. It
   records friction and durable lessons only — a handoff belongs at a
   session boundary, which this is not.

## Gotchas

- When a document's orphan status is unverifiable, leave it in place. An
  unnecessary spec costs a little noise; a wrongly deleted one loses work.
- `index.md` carries no frontmatter — it is a directory listing, not a domain
  document.
- The flat `specs/` layout is the whole story; legacy `views/` directories are
  retired.
- When editing an existing domain document, preserve hand-authored sections
  and apply targeted edits only to sections that changed.
- On the first run, when `specs/index.md` is absent, wipe only the contents
  of `memory-bank/knowledge/specs/` before generation (preserve the directory
  itself) — this is the one-time clean transition from the retired view
  layout.

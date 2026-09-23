# Regenerate domain specifications

Generate one reviewable specification per domain, plus architecture and index
documents. Files under `memory-bank/` are local and can be regenerated. Read the
code directly — every spec is grounded in source you actually read.

## Workflow

1. **Choose where to work.** Run
   `git check-ignore -q <knowledge>/specs/.varde-spec-probe` before
   creating a worktree (a `<knowledge>` outside the repository counts as
   exit `0`). When it exits `0`, run in the caller checkout so
   existing local specifications and Notes remain visible, and so generated
   artifacts stay there. When it exits `1`, isolate per `references/worktree.md`
   using id `spec-<short-id>`, then use its printed `path=` as the effective
   `repoRoot`. This protects tracked specification runs from concurrent source
   edits and preserves normal Git merging. You need not check whether you are
   already nested — creation reuses a caller's worktree on its own.
   State the detected storage mode before continuing. Load
   `references/varde-workflow-cli.md` if `varde-workflow` is on PATH.
   Write, refresh, and delete concepts only through that command.
   Without it, report degraded reads and stop before mutations.
2. **Find domains needing updates.** Load `references/varde-code.md` if that
   CLI is on PATH. Use it first to scope this step: diff against
   the `source_commit` recorded in the prior run's `index.md` (via
   `detect_changes`) rather than scanning the whole repo. Without it, compare
   existing spec documents against the current code structure by reading both.
   Full procedure: `references/spec-plan.md`.
3. **Generate domain documents.** Generate domains one at a time by default.
   Delegate only domains with independent source and output paths, with at most
   three delegates active. Each executor writes exactly one document under
   `<knowledge>/specs/`. When `varde-code` was detected in step 2,
   each executor batches discovery and relationship queries across its domain.
   Read short, known files directly. Use `get_symbol` only for exact symbols
   inside large files. A delegated executor receives the binary path and
   domain changed-file list. Otherwise the executor reads source files
   directly. Before editing any document, load and follow
   `references/spec-format.md` completely. It owns provenance, generated-block
   boundaries, Notes preservation, legacy migration, meaning-layer rendering,
   and the per-agent contract. Generated specifications under ignored storage
   stay local. Tracked specifications remain committed project knowledge.
4. **Delete orphans.** Delete every domain document whose corresponding code
   no longer exists, from the flat specs root (`specs/<slug>` maps to
   `<knowledge>/specs/<slug>.md`). Deletion is confined to `specs/`,
   and to documents you have confirmed are orphans.
5. **Write the index.** After domain generation finishes, write
   `<knowledge>/specs/index.md` deterministically. Index format:
   `references/spec-format.md`.
6. **Verify.** Compare each generated spec with the source it describes. Check
   accuracy and drift manually, then report broken links and orphan files.
   Conditions checked: `references/spec-verify.md`.
7. **Report the summary.** Report domain write/fail/skip counts, deleted orphan
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
  of `<knowledge>/specs/` before generation (preserve the directory
  itself) — this is the one-time clean transition from the retired view
  layout.

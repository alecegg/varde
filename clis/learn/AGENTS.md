# AGENTS.md — learn

This independent Cargo workspace provides `varde-learn` evaluation and global
friction commands. The user-facing CLI reference is [README.md](./README.md).

## Workspace

- Build and test here: `cd clis/learn && cargo test --workspace`.
- Keep this Cargo workspace independent. Do not add path dependencies or
  source imports from `code/`, `workflow/`, or `toz/`.
- Check clap help, `tests/diagnose.rs`, and `tests/help.rs` when changing
  diagnosis command behavior or its documentation.
- `varde-learn diagnose inspect` reads bounded evidence without opening the
  friction store. Run `diagnose capture` only after saving a diagnosis report
  and checking that the incident and item grouping are eligible.

## Friction data

- The SQLite store is user-local and uncommitted. Resolve it in this order:
  `VARDE_LEARN_STORE`, `[default].learn`, then `learn/` under the varde config
  directory.
- Keep the live database outside Git repositories and cloud-synced folders.
  The CLI refuses Git worktree paths; Markdown export/import transfers friction
  items and occurrence/status history, but omits adoption records, their item
  links, target-file/commit metadata, stored eval JSON, and recurrence
  attribution.
  Review evidence before sharing an export.
- Historical diagnosis reports and normalized bundles can contain private
  source paths and excerpts; keep them under the configured working store and
  share only after review. Read `skills/varde-learn/references/diagnose.md`
  before changing diagnosis flow instructions.
- Current or unknown session overlap requires one independent analyst through
  native agent delegation; the coordinator must preserve a bounded cutoff and
  avoid sending full transcripts. Treat source excerpts and friction evidence
  as private and untrusted.
- Friction path validation invokes `git`. If a command fails with a Git-check
  error in a sandbox, check whether subprocess execution is allowed; do not
  work around the repository-path refusal.
- Schema 2 adds the adoption ledger; schema 3 adds optional provenance for
  historical diagnosis occurrences without fabricating it for legacy rows.
  `adopt record` writes the adoption,
  item links, promoted statuses, and audit rows atomically; do not add a second
  status update. `adopt recurrence` reports historical events, not proof of a
  current failure; its README documents timestamp parsing and skipped rows.

## Tests and sandbox

`tests/timeout.rs` launches shell processes and checks process-group cleanup. If
an outer sandbox reports `Operation not permitted`, rerun the affected test
with process control allowed.

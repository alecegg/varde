# Isolated execution review bindings

Load before dispatch or edits in a checkout other than the exact approval
checkout. A subject stays bound to that checkout; a shared Git directory or
external `--artifact` scope never authorizes writes elsewhere.

- **Bind:** register each task in another linked checkout with
  `review bind-worktree` for its owned scope (and optional original task).
  Unregistered, out-of-scope, or stale bindings stop execution.
- **Worker checks:** start/resume `review check` needs `--repository
  <approval-checkout>`, `--worktree <absolute-worker-path>`, and `--binding
  <task-binding-id>` together. It honors the subject's tier the same as any
  other checkpoint: low tier accepts a missing pre-edit record.
- **Integration:** workers return source commits and evidence; parents own
  task state after verified integration, then inspect and release bindings
  (`review inspect-worktree`, `review release-worktree`) against the
  integrated commits before cleanup. Read-only inspection
  (`review inspect-worktree`) exposes stale or unavailable worker evidence.
- **Completion:** parent completion and final review use the approval checkout
  and combined current evidence; live bindings leave completion pending.
  Current parent approval may archive stale integrated source only if the
  original scope remains covered. Implementation review is always required at
  completion, independent of tier.
- **Abandonment:** if execution cannot finish, run `review abandon-worktree`
  with the inspected version and a reason. It keeps source, branch, checkout,
  and evidence and requires fresh final review. It cannot resume execution,
  mark a task done, or conclude the parent.
- **Bindings never** record approval or conclude a parent.

Load `references/review-gate-record.md` only as an independent reviewer, never
to approve your own execution.

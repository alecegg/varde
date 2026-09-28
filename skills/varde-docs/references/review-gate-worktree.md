# Isolated execution review bindings

Load before dispatch or edits in a checkout different from the exact approval
checkout. External `--artifact` scope does not authorize isolated task writes;
worktree ownership remains repository-relative.


A subject remains bound to its exact approval checkout. A task in another
linked checkout requires an explicit `review bind-worktree` registration for
its owned scope and optional original task contract. Pass the parent repository,
worker path and binding ID together to `review check` for start/resume; a shared
Git directory alone is not authorization. Unregistered, out-of-scope or stale
bindings stop execution. Workers return source commits and evidence; parents
own isolated task state updates after verified integration. Inspect and release
bindings against integrated commits before cleanup. Parent completion and final
review use the approval checkout and the combined current evidence; live bindings
leave completion pending. Read-only inspection exposes stale or unavailable
worker evidence. Current parent approval may archive stale integrated source
only if the original scope remains covered. If execution cannot finish, use
`review abandon-worktree` with the inspected version and a reason: preserve
source, branch and checkout, retain evidence, and require fresh final review.
Abandonment cannot resume execution or mark a task done. Do not use a binding
to record approval or conclude its parent.


Worker checkpoint context requires `--repository <approval-checkout>`,
`--worktree <absolute-worker-path>`, and `--binding <task-binding-id>` together.
Return source commits and evidence; parents own task bookkeeping after verified
integration. Load `references/review-gate-record.md` only when acting as an
independent reviewer, never to approve your own execution.

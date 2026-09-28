# Worktree isolation

Mechanics for editing in a separate git worktree and merging back. The calling
procedure decides *whether* to isolate; read-only work never does.

## Who owns the worktree

> `created=true`: you **own** the worktree — finish per the caller's selected
> Merge, Push and open PR, or Keep as is action.
> `created=false`: you're inside a caller's linked worktree — reuse it,
> **never** merge or clean up; the owner does that.

For Merge, merge before asking the user to open or edit files in their
original checkout. For Keep as is or Push and open PR, retain the worktree and
give its path when showing files; do not imply the original checkout contains
those changes.

## Workflow

Scripts (each has `--help`): `worktree-create.sh <id> [base]`, then edit only
inside the printed `path=`; `worktree-merge.sh <id>` (exit 2 = nothing to
merge, 3 = conflict → resolve below, 4 = source or destination branch missing
or invalid — inspect the named refs before retrying, 5 = uncommitted changes —
commit first);
`worktree-cleanup.sh <id>` only after merge exits 0.

`worktree-merge.sh` can run from an integration worktree. It resolves sibling
task worktrees from the repository's shared Git directory, then merges their
branches into the currently checked-out integration branch.

**Resolve conflicts** against an `intent` string explaining the worktree
change (ask for one if the caller supplied none). Run the project's
verification command before committing the merge. Can't resolve without
guessing at intent, or verification fails: `git merge --abort` and report
the unresolved hunks.

## Review authorization for isolated tasks

The approval checkout is the exact repository that owns the subject; a linked
worktree does not inherit authority merely because it shares Git storage.
Before dispatching a task into another checkout, inspect the parent subject
and register the worker from the approval checkout:

```sh
varde-workflow review inspect --subject <subject-id> --phase pre-edit --json
varde-workflow review bind-worktree --subject <subject-id> --binding <task-binding-id> --expected-version <data.version> --worktree <absolute-worker-path> --scope <owned-path> [--scope <owned-path> ...] [--task <absolute-original-task.md>] --json
```

Use the task's declared writes (both rename sides). For a bounded refactor
without a task file, omit `--task` and use its approved bounded scope. A missing,
stale, or rejected binding stops dispatch. Do not initialize a separate subject
for each task or broaden repository identity. Include the approval checkout,
worker path, subject and binding IDs in the executor brief. In the worker,
start and resume use all three context flags together:

```sh
varde-workflow review check --subject <subject-id> --repository <approval-checkout> --worktree <absolute-worker-path> --binding <task-binding-id> --checkpoint start --json
```

A binding authorizes only start/resume within its task scope. The executor
returns source commits and verification evidence; the parent alone updates
tracked and external task files after verified source integration. The worker
must not transition task or plan state, record parent approval, or conclude the
parent. Run ordinary parent gates from the approval checkout.

Capture worker evidence before merging; after the verified commit is integrated
into the approval checkout, inspect again and release using its current version:

```sh
varde-workflow review inspect-worktree --subject <subject-id> --binding <task-binding-id> --json
varde-workflow review release-worktree --subject <subject-id> --binding <task-binding-id> --expected-version <data.version> --commit <worker-commit> --json
```

Release archives separate worker evidence before cleanup. A release failure
retains the worktree and binding for recovery. Parent completion requires all
bindings archived and a current combined implementation review. Keep as is or
Push and open PR retains the live binding and leaves parent completion pending
until integration; report that state and the worktree path.

Renewed approval never authorizes a stale worker to resume. Read-only inspection
still provides its evidence and current version. Release may archive already
integrated, clean source under current parent approval when the original scope
remains covered. Parent task verification and bookkeeping still use the current
contract. If execution is abandoned or the checkout is unavailable, inspect then
archive the binding without deleting its source, branch, or worktree:

```sh
varde-workflow review abandon-worktree --subject <subject-id> --binding <task-binding-id> --expected-version <data.version> --reason "<why execution stopped>" --json
```

Abandonment needs current parent approval, retains available evidence, and
requires a fresh combined final review. It neither integrates source nor marks
a task done. Handle any retained source through a separately approved change.

An enclosing feature checkout that owns its own plan subjects is the approval
checkout for its serial children. Map tracked plan/task paths to that checkout's
physical copies; keep external plans in their configured store. Do not substitute
a main-checkout subject for a feature-checkout subject or copy approval records.

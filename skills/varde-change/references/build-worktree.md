# Worktree isolation

## Who owns the worktree

| `worktree-create.sh` prints | You | Finish |
|---|---|---|
| `created=true` | **own** the worktree | per the caller's selected Merge, Push and open PR, or Keep as is action |
| `created=false` | are inside a caller's linked worktree | reuse it; **never** merge or clean up |

- **Merge:** merge before asking the user to open or edit files in their
  original checkout.

## Workflow

Scripts (each has `--help`):

1. `scripts/worktree-create.sh <id> [base]`, then edit only inside the printed
   `path=`.
2. `scripts/worktree-merge.sh <id>` merges into the checked-out branch; from an
   integration worktree it resolves sibling task worktrees through the shared
   Git directory.
3. `scripts/worktree-cleanup.sh <id>`, only after merge exits 0.

| Merge exit | Meaning | Action |
|---|---|---|
| 2 | nothing to merge | none needed |
| 3 | conflict | resolve below |
| 4 | source or destination branch missing or invalid | inspect the named refs before retrying |
| 5 | uncommitted changes | commit first |

To resolve conflicts:

1. Resolve against an `intent` string explaining the worktree change; ask for
   one if the caller supplied none.
2. Run the project's verification command before committing the merge.
3. If resolving needs a guess at intent, or verification fails, run
   `git merge --abort` and report the unresolved hunks.

## Review authorization for isolated tasks

Binding rules live in `references/review-gate-worktree.md`. Run every command
below from the approval checkout, the exact repository that owns the subject,
except the worker's own checks.

### Register the worker

Before dispatching a task into another checkout:

```sh
varde-workflow review inspect --subject <subject-id> --phase pre-edit --json
varde-workflow review bind-worktree --subject <subject-id> --binding <task-binding-id> --expected-version <data.version> --worktree <absolute-worker-path> --scope <owned-path> [--scope <owned-path> ...] [--task <absolute-original-task.md>] --json
```

- Scope the binding to the task's declared writes, both rename sides. A
  bounded refactor without a task file omits `--task` and uses its approved
  bounded scope.
- Never initialize a separate subject per task or broaden repository identity.
- Put the approval checkout, worker path, subject ID, and binding ID in the
  executor brief. The worker passes all three context flags at start and
  resume:

```sh
varde-workflow review check --subject <subject-id> --repository <approval-checkout> --worktree <absolute-worker-path> --binding <task-binding-id> --checkpoint start --json
```

### Release

Capture worker evidence before merging. After the verified commit is
integrated into the approval checkout, inspect again and release with its
current version:

```sh
varde-workflow review inspect-worktree --subject <subject-id> --binding <task-binding-id> --json
varde-workflow review release-worktree --subject <subject-id> --binding <task-binding-id> --expected-version <data.version> --commit <worker-commit> --json
```

- **Release fails:** keep the worktree and binding for recovery.
- **Keep as is or Push and open PR:** the binding stays live. Report:
  - verified source;
  - parent completion as pending;
  - worktree path.
  Write a handoff.

### Abandon

If execution is abandoned or the checkout is unavailable, inspect, then
archive the binding:

```sh
varde-workflow review abandon-worktree --subject <subject-id> --binding <task-binding-id> --expected-version <data.version> --reason "<why execution stopped>" --json
```

Handle any retained source through a separately approved change.

### Feature checkout

An enclosing feature checkout that owns its own plan subjects is the approval
checkout for its serial children:

- Map tracked plan/task paths to that checkout's physical copies.
- Keep external plans in their configured store.
- Never substitute a main-checkout subject for a feature-checkout subject or
  copy approval records.

## Finish an isolated run

An isolated run may enter at integration choice once source and checks are
verified and only post-integration parent bookkeeping remains. After
Merge/release, all tasks and nested children must be complete before final
review or conclusion.

When this run owns an unmerged isolated checkout, present applicable finish
choices before parent review or conclusion:

- **Merge:**
  1. Integrate verified source.
  2. Release bindings and apply parent-owned task bookkeeping.
  3. Continue with step 1 at the approval checkout.
- **Keep as is** or **Push and open PR:** follow Release.

A caller-owned feature child:

- **Subject in another approval checkout:** return pending integration to its
  owner without a merge choice.
- **Subject in the feature checkout:** conclude locally through its normal
  gates; leave the enclosing merge to the feature owner.

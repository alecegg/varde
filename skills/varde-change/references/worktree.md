# Worktree isolation

Put file edits in a separate git worktree, then merge the result back. Skip
worktree isolation when the operation only reads files.

The calling procedure decides *whether* to isolate. This file covers the
mechanics and decides whether to nest.

## Who owns the worktree

`scripts/worktree-create.sh` handles nested worktrees. Inside an existing linked
worktree, it does not create another one. It prints `created=false` and reuses
the current worktree. Otherwise, it creates a fresh one and prints
`created=true`. Use this rule:

> Run `scripts/worktree-create.sh <id> [base]`. Do all edits inside the printed
> `path=`. If `created=true`, you **own** the worktree: merge and then clean up
> when done. If `created=false`, you reuse a caller's worktree: **never** merge
> or clean up; the owner does that.

**Merge before showing files to the user.** If you own the worktree, merge it
before asking the user to open, review, edit, or approve anything. The user
works in their own checkout and recognizes its paths. Keep interactive document
and approval work there throughout.

## Workflow

1. **Create.** Run `scripts/worktree-create.sh <id> [base]`. It pins the
   worktree to a resolved base SHA instead of a moving branch head. A concurrent
   change to `base` cannot then shift the worktree's starting point. The script
   prints `path=`, `branch=`, and `created=`.
2. **Merge back.** Run `scripts/worktree-merge.sh <id> [into]`. It commits
   uncommitted changes in the worktree, checks that the branch has commits ahead
   of its base, and exits 2 if it does not. It then attempts `git merge --no-ff`.
   Exit 3 means conflict. Go to step 3.
3. **Resolve conflicts.** Follow **Resolving a conflicted merge** below. Keep
   the worktree until resolution succeeds or you report an unresolved conflict.
4. **Clean up.** Once the merge is complete, `scripts/worktree-cleanup.sh <id>`
   removes the worktree and deletes its branch.

A caller that already ran its own merge and hit conflicts can jump straight to
step 3 without ever running `worktree-create.sh`.

## Resolving a conflicted merge

Resolve conflicts with an `intent` string explaining the worktree change. If
the calling procedure did not supply one, ask for it before resolving. Use the
intent to resolve conflicts without guessing.

1. List conflicting files: `git diff --name-only --diff-filter=U`.
2. For each, read both sides (`git show :2:<path>` for ours, `git show :3:<path>`
   for theirs) plus enough surrounding context to understand each side's change.
3. Preserve both sides when their changes do not overlap. For example, keep
   additions to different sections of the same file. Choose one side only when
   the changes are mutually exclusive. State which side won and why in the
   merge summary.
4. Stage the resolution with `git add <path>`. Run the project's existing
   verification command before completing the merge commit. This can be tests,
   typecheck, or another command the repo uses.
5. If verification fails, or if you cannot resolve the conflict without
   guessing at intent, abort with `git merge --abort`. Report the unresolved
   conflict and its specific hunks. Let a human or the calling procedure
   decide what happens next.
6. If verification passes, complete the merge with `git commit`.

## Gotchas

- Use pure git and bash throughout. A harness with native worktree isolation,
  such as Claude's `Agent` `isolation: "worktree"` option, may use that for its
  own dispatch. This procedure is for callers without that option or callers
  that want explicit, inspectable isolation.

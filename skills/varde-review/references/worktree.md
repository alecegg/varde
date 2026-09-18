# Worktree isolation

Put file edits in a separate git worktree, then merge the result back. Skip this
entirely when the operation only reads files.

The calling procedure decides *whether* to isolate. This file only covers the
mechanics — plus one decision of its own: whether to nest.

## Who owns the worktree

`scripts/worktree-create.sh` is idempotent about nesting. Inside an existing
linked worktree it does not nest a second one — it prints `created=false` and
reuses the current worktree. Otherwise it makes a fresh one and prints
`created=true`. That gives every caller one rule:

> Run `scripts/worktree-create.sh <id> [base]`. Do all edits inside the printed
> `path=`. If `created=true`, you **own** the worktree — you must merge and then
> clean up when done. If `created=false`, you are reusing a caller's worktree —
> **never** merge or clean up; the owner does that.

**Merge before showing files to the user.** If you own the worktree, merge
before asking the user to open, review, edit, or approve anything — they work in
their own checkout, at paths they recognize. Interactive document and approval
work belongs there throughout.

## Workflow

1. **Create.** `scripts/worktree-create.sh <id> [base]` pins the worktree to a
   resolved base SHA rather than a moving branch head, so a concurrent change to
   `base` mid-operation cannot silently shift what the worktree was created
   from. It prints `path=`, `branch=`, and `created=`.
2. **Merge back.** `scripts/worktree-merge.sh <id> [into]` commits any
   uncommitted changes left in the worktree, checks the branch actually has
   commits ahead of its base (exit 2 if not), then attempts `git merge --no-ff`.
   Exit 3 means conflict: go to step 3.
3. **Resolve conflicts.** Follow **Resolving a conflicted merge** below. Leave
   the worktree alive until that reaches a terminal outcome.
4. **Clean up.** Once the merge is complete, `scripts/worktree-cleanup.sh <id>`
   removes the worktree and deletes its branch.

A caller that already ran its own merge and hit conflicts can jump straight to
step 3 without ever running `worktree-create.sh`.

## Resolving a conflicted merge

This needs an `intent` string explaining what the worktree change was meant to
do. If the calling procedure did not supply one, ask for it before resolving —
intent is what makes a resolution a judgment rather than a guess.

1. List conflicting files: `git diff --name-only --diff-filter=U`.
2. For each, read both sides (`git show :2:<path>` for ours, `git show :3:<path>`
   for theirs) plus enough surrounding context to understand each side's change.
3. Resolve so both sides' intent survives wherever they do not actually overlap
   (e.g. two additions to different sections of the same file). Pick one side
   over the other only when the changes are genuinely mutually exclusive, and
   state which side won and why in the merge summary.
4. Stage the resolution (`git add <path>`) and run the project's existing
   verification command — tests, typecheck, whatever the repo already uses —
   before completing the merge commit.
5. If verification fails, or a conflict cannot be resolved without guessing at
   intent, abort (`git merge --abort`) and report the unresolved conflict with
   the specific hunks. A human or the calling procedure decides what happens
   next.
6. If verification passes, complete the merge with `git commit`.

## Gotchas

- Pure git and bash throughout. A harness that offers native worktree isolation
  (e.g. Claude's `Agent` `isolation: "worktree"` option) may be preferable for
  its own dispatch — this procedure is for callers and harnesses without that
  option, or that want isolation as an explicit, inspectable step rather than
  implicit tool behavior.

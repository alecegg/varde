---
name: varde-worktree
description: >
  TRIGGER: Isolate a file-producing or file-editing operation in its own git
  worktree so it never collides mid-session with other agents editing the
  same checkout, then merge the result back and resolve any conflicts.
  Invoked as a subroutine by other skills (build, review-fix, simplify,
  etc.) or directly. Pure git/bash — no harness-specific tooling — so it
  behaves the same under any agent runtime.
  SKIP: Skip when the operation only reads files, or when the caller already
  has its own isolation mechanism and just needs conflict resolution (jump
  straight to `references/RESOLVE.md` instead of `create`).
  Example phrases: "isolate this edit in a worktree" or "merge my worktree
  back and resolve conflicts".
---

## Entry point dispatch

| Invocation | Action |
|---|---|
| `create id=<id> [base=<ref>]` | Run `scripts/create.sh <id> [base]`. Prints `path=`, `branch=`, and `created=`. |
| `merge id=<id> [into=<ref>]` | Run `scripts/merge.sh <id> [into]`. Exit 3 means conflict — go to step 3. |
| `resolve id=<id> intent="<text>"` | Follow `references/RESOLVE.md` against the in-progress conflicted merge. Used standalone when a caller already attempted its own merge and hit conflicts. |
| `cleanup id=<id>` | Run `scripts/cleanup.sh <id>`. |

## The ownership rule (callers depend on this)

`create` is idempotent about nesting. If the caller is **already inside a
linked worktree**, `create` does not nest a second one — it prints
`created=false` and reuses the current worktree. Otherwise it makes a fresh
one and prints `created=true`. This lets every caller use one unconditional
rule instead of reasoning about whether it was dispatched standalone or nested:

> Call `create id=<id>`. Do all edits inside the printed `path=`. If
> `created=true`, you **own** the worktree — you must `merge` then `cleanup`
> when done. If `created=false`, you are reusing a caller's worktree —
> **never** `merge` or `cleanup`; the owner does that.

**Merge before you hand files to the user.** A worktree is for autonomous
work that ends in a merge. If you own the worktree (`created=true`) and the
run reaches a point where you direct the user to open, review, edit, or
approve the produced files, you must `merge` back **first** — never point the
user at a worktree path. A skill that is interactive on its files *throughout*
(a live doc loop, a propose-and-approve loop) should not isolate at all; it
works in the current checkout.

## Workflow

1. **Create the worktree.** Run `scripts/create.sh <id> [base]` — it pins
   the worktree to a resolved base SHA rather than a moving branch head, so
   a concurrent change to `base` mid-operation can't silently shift what
   the worktree was created from. Report the printed `path=`/`branch=`/`created=`
   back to the caller. The caller does all its file edits inside that path;
   this step doesn't know or care what happens there.
2. **Merge the worktree back.** Run `scripts/merge.sh <id> [into]`. It
   commits any uncommitted changes left in the worktree, checks the branch
   actually has commits ahead of its base (exit 2 if not — never merge an
   empty branch), then attempts `git merge --no-ff`.
3. **Resolve conflicts, if `merge.sh` exited 3.** Follow
   `references/RESOLVE.md` in full — it requires an `intent` string from the
   caller and walks reading both sides, resolving, verifying, and either
   completing or aborting the merge. Leave the worktree alive until this
   step reaches a terminal outcome.
4. **Clean up.** Once the merge is complete (via step 2 or step 3), run
   `scripts/cleanup.sh <id>` to remove the worktree and delete its branch.

## Gotchas

- This skill never decides *whether* to isolate — that's the calling
  skill's judgment call. It only does the mechanics once asked. But it does
  decide whether to *nest*: `create` no-ops to `created=false` when already
  inside a linked worktree, so callers never hand-roll a "skip if nested" check.
- Leave a conflicted, unresolved worktree alive until a human or the
  calling skill decides the outcome — run `cleanup.sh` only after `merge.sh`
  succeeds or `RESOLVE.md` reaches a terminal outcome.
- Pure git/bash throughout. A caller running under a harness that offers
  native worktree isolation (e.g. Claude's `Agent` `isolation: "worktree"`
  option) may prefer that for its own dispatch instead — this skill is for
  callers and harnesses without that option, or that want isolation as an
  explicit, inspectable step rather than implicit tool behavior.

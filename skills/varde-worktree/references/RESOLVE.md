# Resolving a conflicted merge

Runs only against an in-progress conflicted merge — left by `scripts/merge.sh`
exiting 3, or handed off from a caller's own merge attempt. Requires an
`intent` string from the caller: what the worktree's change was trying to
accomplish. Resolving without it is exactly the blind, silent-clobber failure
mode worktree isolation exists to avoid recreating at merge time — if a
caller asks for resolution with no intent given, ask for it before
proceeding.

1. List conflicting files: `git diff --name-only --diff-filter=U`.
2. For each conflicting file, read both sides of the conflict (`git show
   :2:<path>` for ours, `git show :3:<path>` for theirs) plus enough
   surrounding context to understand each side's change.
3. Resolve so both sides' intent survives wherever they don't actually
   overlap (e.g. two additions to different sections of the same file). Only
   pick one side over the other when the changes are genuinely mutually
   exclusive, and state which side won and why in the eventual merge
   summary.
4. Stage the resolution (`git add <path>`) and run the project's existing
   verification command (tests / typecheck — whatever the repo already
   uses) before completing the merge commit.
5. If verification fails, or a conflict can't be resolved without guessing
   at intent, abort (`git merge --abort`) and report the unresolved conflict
   with the specific hunks — a human or the calling skill decides how to
   proceed from there. Never force through a conflicted merge on a failing
   or guessed resolution.
6. If verification passes, complete the merge: `git commit` (git's default
   merge message is fine unless the caller wants otherwise).

Leave the worktree alive until the merge is fully resolved one way or the
other — `scripts/cleanup.sh` must not run mid-conflict.

# Build a bounded change

Outside refactor posture, create no plan/task files, worktrees, handoffs, or
commits unless escalating to `references/build.md` needs them or the user asks.

## Mechanical edits

A new change whose entire diff meets the mechanical edit exception in
`references/review-gates.md` follows its checks and reporting instead of the
steps below. An existing review subject still requires its checkpoints.

## 1. Gate the change

Before editing:

1. Initialize the subject (`review init --subject <safe-id>`) per
   `references/review-gates.md` §2, keeping review evidence in `<working>`,
   outside the source scope.

2. Low tier with none of review-gates §2 step 3's contract triggers skips the
   pre-edit verdict; otherwise obtain it. Begin only when
   `varde-workflow review check --subject <subject-id> --checkpoint start
   --json` passes.
3. Send a material contract or scope change through `review contract` or
   `review expand` and a fresh verdict.

## 2. Edit, verify, complete

1. Run the contract's verification checks.
2. Complete the independent implementation review, which is always required
   (review-gates §5).
3. Run the `complete` checkpoint before reporting completion.

## One standalone review finding

1. Add its review folder, ID, concrete solution, and decision evidence to the
   contract.
2. Scope its category file and `review.md` too (repeat `--artifact
   <absolute-file>` when outside the repository).
3. After the source fix passes verification, update only that finding's
   `Disposition`, link the bounded subject in its decision note, and recompute
   `review.md`'s `triage_status`.

# Build a bounded change

Create no plan.md. Before editing, write the outcome and verification in
one or two lines to a small `<working>/plans/<date>-<slug>/task.md`, and keep
the review report beside it in `review.md`. Escalate to `references/build.md`
when the change needs a plan or several outcomes.

## Edit and complete

- Work in a fresh task worktree.
- Follow `references/build-execution.md` for checks.
- Run the checks in task.md.
- After they pass, commit the verified owned paths and return the evidence for
  the independent implementation review in `references/review-gates.md`.
- Merge, push, or open a PR only on the user's explicit approval.

## One standalone review finding

Load `varde-review`: use your skill tool, or read `../../varde-review/SKILL.md`,
and follow its fix guidance to record the finding with its concrete solution
and decision evidence, apply it, and update only that finding's status.

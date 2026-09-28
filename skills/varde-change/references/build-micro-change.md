# Build a bounded change

Use this route for a settled single outcome with known verification, regardless
of file count. When dependent outcomes, design, or human choices remain, use
`build-plan.md`.
Inspect targets, consumers, and covering checks together (`varde-code batch`
when several queries matter).
For a behavior-preserving refactor, also follow `references/build-posture-refactor.md`.
Its dedicated worktree, verification, source commit, and merge apply without a
task file. Complete this route's review checkpoint after integration.

For a new change whose entire diff meets the mechanical edit exception in
`references/review-gates.md`, follow its checks and reporting instead of the
review steps below. An existing review subject still requires its checkpoints.

Before editing, write the bounded contract as JSON with outcome, scope,
assumptions, design, open choices, and verification. Resolve `<working>` and
`<knowledge>` once; keep the contract and review evidence in the configured
working store, outside the source scope. Initialize the subject:

```sh
varde-workflow review init --subject <safe-id> --contract <contract.json> --repository <repo-root> --scope <path> [--scope <path> ...] --json
```

For one selected standalone review finding, include its review folder, ID,
concrete solution, and decision evidence in the contract. Scope its category
file and `review.md` too (repeat `--artifact <absolute-file>` when outside the
repository). After the source fix passes verification, update only that
finding's `Disposition`, link the bounded subject in its decision note, and
recompute `review.md`'s `triage_status`. Final review and the complete
checkpoint cover source and review edits. Plan-owned findings still use their
task flow.

Send the returned subject id, repository, and resolved memory paths to an
independent reviewer. The reviewer inspects phase `pre-edit`, resolves
code-answerable questions, assesses verification and structural risk, then
writes and records their own evidence with `review record`. The coordinator
does not create or approve that record. Run
`varde-workflow review check --subject <subject-id> --checkpoint start --json`
and begin implementation only when it is ready. If the contract or scope
changes materially, update it through the OCC `review contract` or
`review expand` command and obtain a fresh verdict.

Edit only the approved scope and run its checks. Complete any required
independent implementation review, then run the `complete` check before
reporting completion. A task under a persisted plan instead inherits its
parent subject; use the task's start/resume route in `build-execution.md`.
If the review CLI is unavailable or rejects its input, stop; do not bypass the
gate with prose approval or a manual file edit.

Outside refactor posture, create no plan/task files, worktrees, handoffs, or
commits unless needed for escalation or requested. A bounded refactor creates
no task file but uses the posture's dedicated worktree and source commit.

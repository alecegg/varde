# Build a bounded change

Use this route for settled scope and a small verification set, even across
several files. When design or human choices remain, use `build-plan.md`.
Inspect targets, consumers, and covering checks together (`varde-code batch`
when several queries matter).

Before editing, write the bounded contract as JSON with outcome, scope,
assumptions, design, open choices, and verification. Resolve `<working>` and
`<knowledge>` once; keep the contract and review evidence in the configured
working store, outside the source scope. Initialize the subject:

```sh
varde-workflow review init --subject <safe-id> --contract <contract.json> --repository <repo-root> --scope <path> [--scope <path> ...] --json
```

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

No plan/task files, worktrees, handoffs, or commits unless needed for
escalation or requested.

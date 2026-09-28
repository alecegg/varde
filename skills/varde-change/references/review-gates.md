# Independent review gates

Apply these gates before implementation changes, including source, configuration,
documentation, fixes, refactors, and prototypes. Read-only investigation and
workflow bookkeeping need no gate. Route edits through `varde-change`.

## Mechanical edit exception

An edit qualifies only if its entire diff corrects spelling, punctuation,
whitespace, or formatting and preserves exact operational meaning. Changes to
commands, paths, conditions, instruction meaning, output contracts,
configuration, code, or tests, and mixed or uncertain diffs, use the full gate.
For an exception, inspect the final diff, run targeted checks, and state why it
qualified and what passed. Skill edits still get `varde-agent-doc-authoring`
review. Existing review subjects keep all checkpoints. If work grows beyond
the exception, use the full gate before making substantive changes.

## Before editing

Give an independent reviewer the outcome, scope, assumptions, open questions,
verification with expected results, and structural risk. Ask it to resolve
code-answerable questions; wait for its verdict before edits. A finding is not
approval of its fix. Persist unresolved human choices and ask only when they
block the implementation; do not reopen decisions the user already made.

For behavior changes, default to a failing test before implementation. The
reviewer may approve a concrete alternative with its rationale and expected
result. Documentation and packaging use suitable structural or smoke checks.

For bounded work, store a JSON contract with outcome, scope, assumptions,
design, open choices, and verification in the configured working store:

```sh
varde-workflow review init --subject <safe-id> --contract <contract.json> --repository <repo-root> --scope <path> --json
```

`--scope` is repository-relative and repeatable. For standalone external
artifacts, use repeatable `--artifact <absolute-file>` instead of or alongside
`--scope`; name each file explicitly, including planned files. Artifact scope
covers files outside the repository, including external working memory; it
cannot cover directories, filesystem aliases, or review-gate evidence. Keep repository
files under `--scope`. At least one scope or artifact is required.

Pass the returned subject id, repository, and resolved memory paths to the
reviewer. The reviewer inspects and records its own evidence; coordinators
must not enter reviewer records or substitute prose approval:

```sh
varde-workflow review inspect --subject <subject-id> --phase pre-edit --json
varde-workflow review record --subject <subject-id> --expected-version <data.version> --file <reviewer-record.json> --json
```

Load only the branch needed:

- Reviewer: load `references/review-gate-record.md` before writing evidence in
  either phase (pre-edit or implementation).
- Persisted plan or contract/scope mutation: load
  `references/review-gate-plan.md` before initialization or mutation.
- Different execution checkout: load `references/review-gate-worktree.md`
  before dispatch or editing there. A subject binds its exact approval checkout;
  sharing a Git directory never substitutes for registration.

If no independent reviewer or required CLI operation is available, stop
implementation. No self-approval, hand-edited record, or manual fallback.

## Execution and completion

Run `varde-workflow review check --subject <subject-id>` with
`--checkpoint start --json` before edits, `--checkpoint resume --json` before
resuming, and `--checkpoint complete --json` before reporting completion.
Never proceed with missing, blocked, stale, or rejected approval. Exit 4 is a
typed gate blocker; exit 3 is an OCC conflict. Resolve blockers or refresh
reviewer evidence, then retry. Material scope, assumption, design, or
verification changes require a fresh independent verdict.

Require independent final review for shared contracts (including workflow
instructions), cross-module or security-sensitive changes, and broad downstream
impact. Record the reason for requiring or skipping it. Use dependency evidence
plus source inspection; partial or empty coverage never proves isolation.
Finish source, docs, and verification before review. The reviewer inspects phase
`implementation` and records evidence covering the whole current subject change.
Run the complete checkpoint afterward. If covered files change, rerun affected
checks and refresh required final evidence.

Use `varde-agent-doc-authoring` for agent documents and `varde-review report`
for code. Behavior-changing or risky review fixes need fresh independent
approval; otherwise targeted verification suffices. Do not recursively invoke
unrelated reviews after findings and checks are resolved.

# Optional `varde-workflow` CLI

`varde-workflow` is an optional Rust tool on PATH for ordinary read-only
workflow operations. Its review commands and gated transitions are required
for implementation work.

It validates workflow state and dependencies; it is not the write path. Write
plans, tasks, and handoffs with Write/Edit whether or not it is installed.
Without it, read-only inspection may use Read/Grep. Do not perform gated
implementation or completion transitions by editing status fields manually.

## The workflow state machine

States are fixed by the workflow schema. An unknown status (`draft`, or a task
in `backlog`) makes every later CLI call fail with `unknown status`.

| Artifact | States | Initial | Legal moves |
|---|---|---|---|
| `plan` | `backlog`, `active`, `blocked`, `completed` | `backlog` | `backlog`→`active`/`blocked`; `active`→`blocked`/`completed`; `blocked`→`active`; `completed` is terminal |
| `task` | `todo`, `in_progress`, `blocked`, `done` | `todo` | `todo`→`in_progress`/`blocked`; `in_progress`→`blocked`/`done`; `blocked`→`in_progress`; `done` is terminal |

No shortcut moves: a task never `in_progress` cannot reach `done`, and a plan
left in `backlog` cannot reach `completed`.

With the CLI, change state through `transition`, never by editing `status`:

```bash
varde-workflow readiness <plan.md> --json          # data.actions, data.blockers, data.ready
varde-workflow graph <any-sibling>/plan.md --json  # data.nodes, data.edges, data.schema
varde-workflow transition <artifact.md> <state> --json
varde-workflow validate <artifact.md> --json       # diagnostics, no mutation
```

## Review evidence and checkpoints

Create one subject and immutable baseline before implementation. Plan subjects
bind a persisted plan; bounded subjects bind a JSON contract. Both require an
explicit repository root and one or more repository-relative scopes:

```sh
varde-workflow review init --plan <plan.md> --repository <repo-root> --scope <path> [--scope <path> ...] --json
varde-workflow review init --subject <safe-id> --contract <contract.json> --repository <repo-root> --scope <path> [--scope <path> ...] --json
```

`init` returns the inspection payload: the subject id is
`data.subject.subject_id` and the revision is `data.version`. Pass the id and
the parent-resolved memory paths to the independent reviewer. Reviewers inspect the current evidence and write
their own JSON record; the coordinator does not approve or write it:

```sh
varde-workflow review inspect --subject <subject-id> --phase pre-edit --json
varde-workflow review record --subject <subject-id> --expected-version <data.version> --file <reviewer-record.json> --json
varde-workflow review check --subject <subject-id> --checkpoint <checkpoint> --json
varde-workflow review contract --subject <subject-id> --expected-version <revision> --file <contract.json> --json
varde-workflow review expand --subject <subject-id> --expected-version <revision> --scope <path> [--scope <path> ...] --json
```

`inspect` returns `version`, `contract_fingerprint`, `baseline_id`, and the
complete current change fingerprint. `record` requires the exact inspected
version and stores reviewer-authored evidence in the configured working store.
Pre-edit evidence includes verdict, unresolved choices, rationale,
verification approach/rationale/expected results, structural-risk assessment
and rationale, and whether final review is required. Implementation evidence binds the
current change fingerprint and `coverage: entire-subject-change`. Use
`review contract` or `review expand` with `--expected-version` for bounded
subject changes; these commands invalidate previous approval as applicable.

`check` reports `ready`, typed `blockers`, and consumed revisions. A blocked
review exits 4; an OCC conflict exits 3; infrastructure errors exit 1.
The checkpoint value is `start`, `resume`, or `complete`.
`readiness` keeps dependency availability (`planning_ready`) separate from
review-gated implementation availability (`implementation_ready`). Planning
and selection can continue with missing approval; implementation cannot.
Transitions and `conclude` enforce the same checkpoints before writes.

The review CLI is not an optional fallback. If the binary, review subcommand,
or required checkpoint is unavailable, stop implementation or completion and
report the missing capability. Never replace approval with prose, manually
write the evidence file, or bypass a gate by editing status.

Run `graph` on **a sibling, not the parent**: given a group `plan.md` it
returns one node and no edges. A rejected transition (`workflow_blocked`) lists
the allowed states and changes no bytes; `recover --root <project-root>`
finishes an interrupted accepted one.

After every criterion and observed spec passes, run `conclude`. Use
`conclusion-status`, `conclusion-retry`, and `conclusion-action` (actions:
`reflection`, `friction`, `handoff`) for follow-up.

The fallback below applies only to reads and planning/bookkeeping. It never
applies to review evidence commands or gated implementation/completion
operations; if unavailable, stop those operations.

## Bound worktrees

For isolated task registration, checks, separate evidence and release, load
`references/worktree.md`. Ordinary subject commands keep exact repository
identity. Start/resume worker checks require `--repository`, `--worktree`, and
`--binding` together; binding context cannot complete a parent. State transitions
and final review run at the owning approval checkout after source integration.

## Fallback rule

Sandbox denial: retry once with escalated access, command unchanged; if that
fails, or the CLI errors, use Read/Grep and Write/Edit and name the lost
capability once.

A command that answers `ok: false` with a validation code is a result, not an
outage: fix the cause instead of routing around it.

Never build or install the binary during another workflow.

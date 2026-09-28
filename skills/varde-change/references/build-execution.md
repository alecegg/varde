# Execution Reference

Every executor reads this before its first tool call. It is the task cycle
every implementation task runs.

Apply `references/review-gates.md` before implementation edits and at
completion. Reuse an unchanged approved plan verdict supplied by the caller.
For persisted work, the parent passes the plan subject id and resolved memory
paths. Tasks inherit that subject; do not initialize or record approval for
yourself. Before the first edit, run:

```sh
varde-workflow review check --subject <subject-id> --checkpoint start --json
```

On resume, run the same command with `--checkpoint resume` before continuing
interrupted work. Stop on a typed blocker. A verified task may become `done` while the
plan's required aggregate implementation review is pending; do not mark the
plan complete on that basis.

When the execution checkout differs from the approval checkout, use the
caller-supplied registered binding. Add `--repository <approval-checkout>`,
`--worktree <absolute-worker-path>`, and `--binding <task-binding-id>` together
to start/resume checks. Load `references/worktree.md` for this contract. Stop
if the context is missing or rejected; ordinary parent checks from the worker
are not a substitute. Keep all isolated task state writes parent-owned.

## Choose the task kind

`kind: research`: write the `creates` doc from primary sources outside the
repo, citing each claim (URL, spec section, file:line); a decision ends with
one recommendation. Then run Completion. Anything else is an implementation
task. A task from the debug path also keeps `debug_evidence` per
`references/build-posture-debug.md`'s Evidence contract.

## Load the posture

Before the first edit, load the reference matching the task's posture: `debug`
→ `references/build-posture-debug.md`; `refactor` →
`references/build-posture-refactor.md`. `spike` posture reverts its own edits
and skips the Completion commit step. `plan-execution` runs this cycle as
written.

## Drift check

Before editing, check the task's `modifies`, `creates`, and both paths in each
`renames` entry against the working tree. Uncommitted or unexpected changes,
or a `creates` path that already exists, are drift. Note benign drift
(unrelated exports, cosmetic renames) and proceed; drift that invalidates the
task's assumptions is a blocker.

## Profile-specific testing

Use the independently approved verification approach from
`references/review-gates.md`; record any alternative and its reason.

`tdd` failing test first · `regression` reproduce, then assert · `characterization`
pin current behavior before editing · `smoke` narrowest start/build check ·
`not-applicable` run the named structural checks and say why.

Except in `refactor` posture, refactoring stays outside this cycle, in the
`varde-review simplify` stage.

Map each `#### Verification` check to a coverage area, then write the test that
best expresses it. A check that resists any coverage is the real mis-scope
indicator: mark the task blocked and stop.

Expected values come from an independent source of truth — a known-good
literal, a worked example, the spec. An assertion that recomputes its expected
value the way the code does is tautological: it passes by construction and can
never disagree with the code.

Before editing a shared surface, check its dependents (`dependents` or
`blast_radius` when `varde-code` is available, targeted grep otherwise). A file
you must write outside `modifies`/`creates`/`renames` is a blocker: stop and
report it rather than widening the task, because a sibling executor may own
it.

A UI check needs a browser tool from your own tool list, else `unavailable`;
never infer rendering from HTTP or source. Log in only with credentials the
user supplied, and submit no form that changes real data.

## Blockers

In any isolated execution worktree, report `blocked`, the reason and verification
evidence without editing the task file; the parent records task state/Progress.
In the owning approval checkout, serial or inline execution runs
`varde-workflow transition <task.md> blocked --json`, logs the reason in the
task's `#### Progress`, and stops. Parallel workers always return blockers to
the parent.

## Completion

In a parallel wave or any isolated execution worktree, report status and
verification evidence; do not write the task file. The parent owns tracked,
untracked and external task status/Progress updates after verified source
integration. In the owning checkout, serial/inline tasks keep their normal
bookkeeping ownership. A spike records question/approach/answer and restores
its own exploratory source edits before reporting completion.

1. When the task's diff exceeds ~40 changed lines or adds a new abstraction,
   run `varde-review simplify` scoped to its uncommitted changes.
2. Run the project's configured lint or scan tooling after source edits outside
   `<working>`/`<knowledge>`. Its findings are a candidate list, never a completion gate:
   fix real issues; skip only false positives or rules flagging correct code.
3. Verify every `#### Verification` check: each `assert:` command must match its
   stated expectation, and each `retrieve:` command's output must be read.
4. Only then move the task to `done` (from `in_progress`; move it there first
   if still `todo`) (`varde-workflow transition <task.md> done
   --json` when on PATH) and end its `#### Progress` with `- evidence: <what you
   ran and what it showed>` — so a resumed or checking run finds where it
   stopped. Name the checks you actually ran, not the profile's nominal stages.
   For any isolated task, defer this transition and task Progress writes to
   the parent until source integration succeeds, whether the task file is
   tracked, untracked or external. Report the evidence instead.
5. For a spike, commit no source changes; its reverted exploration and recorded
   evidence establish completion. Otherwise commit the task's source paths
   with a message referencing the task ID. Include its tracked task file only
   in the owning checkout; isolated workers commit source only and leave task
   bookkeeping to the parent after integration. Use `git revert` to undo a
   completed implementation task.
6. Report the result and any obstacle you hit (failed command, stale guidance,
   workaround); the orchestrator records lessons at the finish.

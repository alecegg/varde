# Execution Reference

Read at the start of every plan. It captures the execution discipline for
implementing tasks.

## Choose the task kind

A task with `kind: research` follows `references/build-research-task.md` instead
of the cycle below — it produces a lasting external output (decision record,
prototype, reference doc), so there is no failing test to write. Anything else
is an implementation task.

## Drift check

Once per plan run, before the first task, check that the plan's
assumptions still hold. Derive the baseline from git: for a tracked plan, its
authoring commit (`git log -n1 --format=%H -- <plan-path>`); otherwise the HEAD
the run started from. Skim the files named in the plan's scope for drift since
then, with `detect_changes` for symbol-level precision or
`git log --oneline -- <paths>`.

Before each task's execution frame, check its `modifies` and
`creates` against the working tree — uncommitted or unexpected changes, or a
`creates` path that already exists, are drift.

Benign drift (unrelated exports, cosmetic renames) gets a note and you proceed
with current reality. Drift that invalidates the plan's assumptions is a
blocker. This is a judgment call, not a mechanical check.

## Profile-specific testing

Use profile-specific testing from the task's declared profile.

- `tdd`: write or update a failing test, implement the smallest change, then
  verify. Failing-pattern tests are valid for existing production code.
- `regression`: reproduce the reported failure, add the regression assertion,
  implement the fix, then verify the failure stays fixed.
- `characterization`: pin current behavior at an existing seam, make the
  scoped change, then verify the characterization still holds.
- `smoke`: run the narrowest start, build, or load check first, then verify the
  changed behavior with focused checks.
- `not-applicable`: run the structural or retrieval checks named by the task.
  Record why no executable test applies.

Strict TDD adds ordered evidence when selected. Add these fields below the
task's profile and rationale:

- `strict_tdd: required` with `profile_source: user` or `repository` requires
  three `tdd_evidence` Progress markers in this order: `stage=red`,
  `stage=green`, then `stage=verify`. Each marker must report `result=pass`
  and a non-empty note.
- `strict_tdd: waived` with `profile_source: user` records a direct waiver.
- `strict_tdd: not-required` with `profile_source: decomposition` keeps the
  decomposition-selected profile without strict evidence.
- `strict_tdd: exception` requires `profile: not-applicable`,
  `profile_source: exception`, and a non-empty `exception:` reason. Its
  structural evidence still uses the `not-applicable` profile checks.

The validator rejects missing, reordered, or undeclared strict evidence.

Refactoring remains outside this cycle. Run it in the
`varde-review simplify` stage that runs after implementation.

Record one concise marker in `#### Progress`:
`- evidence: profile=<profile>; checks=<profile checks>; result=pass;
note=<short result>`. The required profile checks are `red,green,verify` for
`tdd`; `reproduce,fix,verify` for `regression`; `characterize,verify` for
`characterization`; `smoke,verify` for `smoke`; and
`not-applicable,structural` for `not-applicable`.

Before writing a new test, find what already covers the file (`tests_for_file`,
or the project's test-file convention). Use existing seams by default and follow
nearby tests. Ask the user only when test placement would choose a new public
contract or materially change the testing strategy.

Before editing an existing surface, compare the discovered impact with the
task's declared `verification_resources`. If a `dependents` or `blast_radius`
result names a consumer outside that ownership and evidence set, stop and
report the new path. Do not widen the task or continue execution silently.
Narrow the task or update its impact evidence through planning first.

Read short, known files directly. Use `get_symbol` only for exact symbols
inside large files. Use Varde Code for relationships, test discovery, or
several related targets. Batch those related lookups.

Expected values come from an independent source of truth — a known-good literal,
a worked example, the spec. An assertion that recomputes its expected value the
way the code does is tautological: it passes by construction and can never
disagree with the code.

Map each of the task's `#### Verification` checks to a coverage area, then name
and write the test that best expresses it — a check does not need a test-function
name decided before you have seen the code. A check that resists any coverage at
all is the real mis-scope indicator: mark the task blocked and stop.

Plan-level acceptance criteria are the whole change's contract, verified once at
the end (`references/build-plan-run.md` Section F), not per task.

## Debug entry integration

When a task comes from `references/debugging-entry.md`, preserve its evidence
state separately from task progress:

- `debug_mode: diagnose` never writes production source. It may write a report
  or task-local evidence artifact when the request allows it.
- `debug_mode: fix` cannot enter implementation until `debug_evidence`
  contains non-empty `reproduction`, `hypotheses`, and `experiments` fields.
- Completion requires non-empty `cause` and `verification` fields. Final
  verification reruns the original reproduction and the regression check.
- Record `route_source` as `automatic` or `explicit` so later review can tell
  why the debugging entry was selected.

If a required field is missing, stop before mutation and report the missing
evidence. Do not replace it with a passing smoke check.

## Given / Unknowns / Plan / Verification

Before any tool call, write a short execution frame.

- **Given** — the current state of the code and test baseline. Establish it by
  reading the symbols in `modifies` before editing; that body is both your
  evidence and the targeted edit's `old_string`. Files in `creates` don't exist
  yet.
- **Unknowns** — open questions blocking a confident next step. Cap at two. More
  than two means the task is mis-scoped.
- **Plan** — the ordered tool calls you intend to make. Revise after every call
  that changes your mental model.
- **Verification** — the command that will demonstrate the task's checks pass.

Resolve one unknown fully before opening the next. Every tool call must either
resolve an unknown, write a failing test, or verify completion. If it does none
of these, revise the plan before continuing.

## Blockers

A blocker prevents the task's `#### Verification` from passing
without out-of-scope work. Set `status: blocked` in the task's own file, append
the reason to its `#### Progress`, and stop. Do not redesign inline or attempt
pre-condition fixes — the planner decides how to unblock.

When the plan's own assumptions no longer hold (found during the drift check,
before any task is dispatched), that is plan-wide: move `plan.md` to `blocked`
and stop. With `varde-workflow` on PATH, use
`varde-workflow transition <plan.md> blocked --json` so the state machine
validates the move and the write goes through the recoverable journal; edit the
frontmatter directly only when the CLI is absent
(`references/varde-workflow-cli.md`). A task worker reports on its own task file and lets the
orchestrator decide whether it escalates.

If the same approach fails repeatedly — a test that will not converge after
three attempts — stop and reassess rather than trying again.

## Static analysis

Whatever lint or scan tooling the project has configured is a candidate list,
never a completion gate. Run it after source edits outside `memory-bank/`, using
the project's own scripts. Fix the real issues; skip a finding only when it is a
genuine false positive or an over-aggressive rule flagging correct code — do not
force-fix correct code to satisfy a rule.

## Completion

Verify every task `#### Verification` check. Each `assert:` command must match
its stated expectation, and each `retrieve:` command's output must be read.
Only then move the task file to `done` — with `varde-workflow` on
PATH, `varde-workflow transition <task.md> done --json`, which rejects the move
if the task is not in `in_progress` and so catches a task that was never
properly started. Then append a one-line entry to its `#### Progress`. Validate
the profile and marker with `scripts/validate-task-evidence.sh <task.md>`. That
marker is the task's execution evidence, which a resumed or checking run reads.

Commit the task's source paths with a message referencing the task ID, including
its `tasks/<task-id>.md` file when plan storage is tracked. Use `git revert` to
undo a completed task.

A verify-only run skips execution entirely: it loads the plan's tasks and runs
each one's `#### Verification` checks, reporting pass or fail without dispatching
work, deriving readiness, or enforcing dependency order.

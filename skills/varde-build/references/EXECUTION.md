# Execution Reference

This reference is read by the main build agent at the start of every plan. It captures the execution discipline for implementing plan steps with TDD. The main agent has no hard step cap, but should still terminate gracefully when work is complete.

## Plan Staleness Check

Before the first task's briefing, once per plan run, sanity-check that the
plan's assumptions still hold: skim the files named in the plan's scope for
drift since the plan was written. If the `varde-code` CLI is available
(`references/VARDE-CODE-CLI.md`), run `detect_changes` against the plan's
authoring commit for symbol-level precision; otherwise use
`git log --oneline -- <paths>`. If nothing changed, proceed silently. If the
files changed but the drift looks benign (unrelated exports, cosmetic
renames), note it and proceed. If the drift invalidates the plan's
assumptions, apply Blocker Handling and stop. This is a judgment call, not a
mechanical gate — there's no stored baseline to diff against.

## Task kind dispatch

Check the task's `kind` field before choosing an execution path:

- **`kind: "research"`** — follow `references/RESEARCH-TASK.md` instead of the TDD Cycle below. A research task produces a durable external output (decision record, prototype, reference doc); no failing test to write, no production code to change.
- **`kind: "implementation"` (default, or absent)** — follow the TDD Cycle below.

## Baseline Conflict Check

Immediately after loading a task section, before the Given / Unknowns / Plan / Verification frame:

- Check the task's `modifies` and `creates` fields against the current working tree: for each `modifies` entry, run `git diff <plan's authoring commit>..HEAD -- <file>`, `git diff -- <file>`, and `git diff --cached -- <file>`; check whether each `creates` path already exists unexpectedly.
- Treat unexpected changes or file existence (including uncommitted changes) as drift.
- On drift, inspect the task body and diff directly. Delegate a read-only pass
  only when fresh context could change the conclusion.
- If the investigation finds a real conflict, apply Blocker Handling and stop.
- If it finds benign drift, note it and proceed with current reality — there's no baseline record to refresh.

The plan's authoring commit (recorded when the plan was written, e.g. in its frontmatter or Progress log) is the reference point for this comparison. Do not update it during execution.

## TDD Cycle

- Before writing a new test, check what already covers this file — if the `varde-code` CLI is available (`references/VARDE-CODE-CLI.md`), run `tests_for_file` to find existing covering test files instead of guessing the location/name; otherwise grep for the project's test-file convention.
- Write or update a failing test first, then implement the smallest change that satisfies it, then run verification until it passes.
- Failing-pattern tests are acceptable when the production code already exists; do not invent production code just to write a test.
- Map each of the task's `#### Verification` checks to a coverage area, then use your judgment to name and write the test(s) that best express it — a check doesn't need a predictable test-function name decided before you've seen the code. A check that resists any test coverage at all (not just a predictable name) is the real mis-scope signal: mark the task blocked and stop. (Plan-level acceptance criteria are the whole change's contract, verified once at the end — `PLAN-RUN.md` Section F — not per task.)

### Seams — where tests go

**Use existing test seams by default.** Follow nearby tests and the project's
conventions. Ask the user only when test placement would choose a new public
contract or materially change the testing strategy.

### Rules of the loop

- **Red before green.** Write the failing test first, then only enough code to pass it. Don't anticipate future tests or add speculative features.
- **One slice at a time.** One seam, one test, one minimal implementation per cycle.
- **Refactoring is not part of the loop.** It belongs to the `/varde-simplify` stage that runs after this task's implementation completes (`DISPATCH.md`), not the red → green implementation cycle.

## Given / Unknowns / Plan / Verification

- Before any tool call, write a short execution frame: Given, Unknowns, Plan, Verification.
- **Given** is the current state of the code, the test baseline, and any relevant prior context the task body already establishes. Establish it by reading the relevant symbols before editing — if the `varde-code` CLI is available (`references/VARDE-CODE-CLI.md`), use it to survey each file in `modifies` and pull the exact body of the symbol about to change, since that body is both your Given-section evidence and the targeted edit's `old_string`. Otherwise, read the file directly and grep for the symbol. Files in `creates` don't exist yet, so this doesn't apply.
- **Unknowns** are open questions that block a confident next step. Cap at two. If you have more than two, the plan step is mis-scoped.
- **Plan** is the ordered set of tool calls you intend to make; revise it after every call if the result changes your mental model.
- **Verification** is the command or check that will demonstrate the task's `#### Verification` checks pass (the test name, the lint pass, the CLI output, etc.).
- Resolve one unknown fully before opening the next. If a tool call neither resolves an unknown, writes a failing test, nor verifies completion, revise the plan before continuing.

## Blocker Handling

- A blocker is a condition that prevents the task's `#### Verification` from passing (or a plan-level acceptance criterion from being satisfiable) without out-of-scope work.
- A task-specific blocker (this task's `#### Verification` can't pass) is owned by the task worker: edit the task's own `tasks/<task-id>.md` frontmatter directly, changing `status:` to `blocked`, append the reason to that task's own `#### Progress` section, then stop. The task worker never edits `plan.md` for this.
- A plan-wide blocker (the whole plan's assumptions no longer hold, e.g. found during the Plan Staleness Check before any task is dispatched) is owned by the orchestrator: edit the plan's `plan.md` frontmatter directly, changing `status:` to `blocked`, and stop. A task worker must never set plan-level `blocked` itself — it reports a task-specific blocker on its own task file, and the orchestrator decides whether that escalates.
- Do not redesign inline or attempt pre-condition fixes. Stop and surface the blocker clearly; the planner decides how to unblock — via a new plan or updated steps.

## Friction

- If the same approach fails repeatedly, stop and reassess the plan.

## Completion

- Before marking a step done, stage only this task's own changed paths explicitly (`git add <path> <path> ...`) plus its own `tasks/<task-id>.md` file, and `git commit` with a descriptive message referencing the step ID. This preserves unrelated hunks in the local default, including run-state and other task files. Keep committed task history intact: use `git revert` when a completed task must be undone.
- Verify the task's `#### Verification` checks pass before marking done. Never mark a step done with untested or failing code.
- Signal task completion by editing the task's `tasks/<task-id>.md` frontmatter directly, setting `status: done`.
- Append a one-line entry to that same task file's own `#### Progress` section directly: `- <one-line summary>`. This is the task's execution evidence — the completion summary a resumed or auditing orchestrator reads.
- Commit the task file together with its source changes in the same commit (`git add memory-bank/working/plans/<plan-id>/tasks/<task-id>.md <source-paths> && git commit -m "task: mark <task-id> done"`). The task file must never sit uncommitted. **Never stage or commit `plan.md` or the run-state file from task execution** — those are orchestrator-owned; committing them would clobber dispatch, retry, and completion tracking.

## Static Analysis / Lint Gate

Whatever static-analysis, lint, or scan tooling the project already has configured never blocks task completion on its own, but its findings are a candidate list to triage. Run it after code edits when source files changed outside `memory-bank/`, using the project's existing scripts (e.g. `npm run lint`, a configured scanner). If the `varde-code` CLI is available (`references/VARDE-CODE-CLI.md`), also run its `scan` rule-pack pass over the changed files as an extra candidate source — same read-only, non-blocking treatment.

Triage each finding: fix the real issues before completing the task. Skip a finding only when it's a genuine false positive or an over-aggressive rule flagging correct code — do not force-fix correct code. Memory-bank-only changes do not require scanning.

## Step Awareness

- The main agent has no hard step cap.
- Even without a hard cap, terminate gracefully when work is complete: run the verification command, confirm it passes, signal step completion, and stop.
- If the same approach is failing repeatedly (e.g. a test that does not converge after three attempts), stop and either revise the plan substantially or mark the plan blocked.

## Verify sub-step (persisted result)

Verify one task's own output and persist the result.

1. Inspect the optional `#### Verification` section. Run every `assert:` command and verify its output matches the stated expectation. Then run every `retrieve:` command and use its output as LLM context. Skip checks when the section is absent.
2. Set `verified: passed` in the task file's frontmatter when all checks pass. Set `verified: failed` when any check fails. Edit the field directly.
3. Preserve the existing retry, escalation, and blocking semantics for failures. Do not change the task's verification checks or `status` handling.

The standalone `mode=verify plan=<id>` entry point skips the Execute step entirely. It loads the plan's tasks and invokes this Verify sub-step only for tasks whose `verified` field is missing or not `passed`. It does not dispatch tasks, derive readiness, inspect `depends_on`, or enforce dependency ordering, and uses the same failure semantics.

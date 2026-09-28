# Build a plan or larger change

## Choose the starting action

| The request is | Start |
|---|---|
| An ask to build, with no plan named | Discover ready plans per `references/build-plan-run.md`, present them, then run the one selected. |
| A named plan with no task files and one bounded outcome | Write one task from `assets/TASK-TEMPLATE.md` (plan AC → its Verification); otherwise decompose per step 4. |
| Any other ad-hoc description — "add a --json flag to the export command" | No plan exists: create one (step 2), confirm it once, then decompose and run it. |
| A behavior-preserving cleanup of a named target | Run the whole pass under the refactor posture (step 4). |

A user may ask to stop before `references/build-plan-finish.md`.

## Workflow

This skill runs **one plan**: tasks in dependency order in one working
location, each delegated to an `executor` per `references/build-dispatch.md`.

1. **Read** `references/build-plan-run.md`, and `references/interview.md`
   when interactive; `references/varde-code.md` only for discovery or
   relationship questions.

2. **Select or create the plan.** Build a named plan. For an ad-hoc
   description, derive a plan-id, create a fresh plan directory, and write a
   minimal `plan.md` — best-guess Problem/Solution and a few Given/When/Then
   plan-level acceptance criteria — and confirm it in one turn. For a large or
   uncertain change, recommend `varde-change plan` instead.

3. **Choose the execution location.** Default to the current checkout and stage
   only task-owned paths. Run `git check-ignore -q
   <working>/plans/<plan-id>/plan.md` once: ignored plan files stay local and
   never enter a commit; tracked ones follow the execution worktree into
   scoped commits. A task with `refactor` posture switches to the dedicated
   worktree in `references/build-posture-refactor.md`; isolate other tasks per
   `references/worktree.md` only when the user asks or a concrete
   concurrent-edit risk makes the checkout unsafe — state the reason first; its
   `created=` result decides who merges. `execution=<auto|serial|inline>`
   (default `auto`); dispatch per `references/build-dispatch.md`.

4. **Decompose and state a posture.** Unless the plan already has task files,
   decompose per `references/build-decomposition.md`, which owns the pause
   rule. Select each task's posture from its title,
   context, and its `#### Out of scope` section, state it, and pass it in the
   dispatch brief (`references/build-dispatch.md`).

   | Posture | Select when | Cadence |
   |---|---|---|
   | plan-execution | Default | The `references/build-execution.md` cycle |
   | spike | The goal is answering one design question, not implementing it | Throwaway code answering one question; run serially, record question/approach/answer and verification in Progress, revert own source edits, commit no source |
   | debug | A known bug or regression is the only goal | `references/build-posture-debug.md` |
   | refactor | Behavior-preserving restructuring, the task's `#### Out of scope` section forbids behavior change, or complexity/readability review findings | `references/build-posture-refactor.md` |

5. **Run tasks** per `references/build-plan-run.md`; read
   `references/build-execution.md` whenever `execution=inline` or no
   `executor` agent is available — the task cycle still runs.

6. **Finish** per `references/build-plan-finish.md`.

## Gotchas

- A task-specific blocker marks that task `blocked` in its own file. A plan-wide
  blocker marks `plan.md` `blocked` and is the orchestrator's call.

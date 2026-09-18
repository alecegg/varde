# Build mode

## Where to start

| The request is | Start |
|---|---|
| A clear micro-change — "rename this label" | Make the edit, run the narrowest relevant check, report. No plan, task, or commit. |
| An existing plan to execute, named or implied | Decompose its spec and acceptance criteria into tasks, then run all tasks in dependency order. |
| An ask to build, with no plan named | Discover ready plans per `references/build-plan-run.md`, present them, then run the one selected. |
| Any other ad-hoc description — "add a --json flag to the export command" | No plan exists: create a short `plan.md` with Problem, Solution, and plan-level acceptance criteria. Confirm it once, then decompose and run it. See step 2. |
| Evidence only, with no implementation — "check whether plan X actually passes" | Skip steps 5–8 and run each task's `#### Verification` checks only (`references/build-execution.md`). |
| A behavior-preserving cleanup of a named target | Run the whole pass under the refactor posture (step 4). |

A caller may ask for the plan to run through step 6 and stop before review and
completion. That deferred finish stops before Section F's review
(`references/build-plan-run.md`).

When invoked by `varde-change orchestrate` with an owned worktree, use that
location.

## Workflow

This skill runs **one plan**, executing its tasks **sequentially in dependency
order** in one working location. The current checkout is the default. One task
at a time keeps context clean and usage predictable. Wall clock is not
optimized; large work is split into small plans at plan time and run in order
(by the user, or by `varde-change orchestrate`).

1. **Load the references.** `references/build-plan-run.md` (how plans and tasks
   are discovered and run) and `references/build-interview.md` (harness
   detection, prompting format, recommendation requirement). Load
   `references/varde-code.md` if that CLI is on PATH, for operations that
   replace some Read/Grep steps here and in `references/build-execution.md`.

2. **Select or create the plan.** If the user named an existing plan, build it.
   If the user gave a free-text change description with no plan (**ad-hoc
   entry**), create one now: derive a plan-id, create a fresh plan directory,
   and write a minimal `plan.md` — a best-guess Problem/Solution plus a short set
   of plan-level acceptance criteria in Given/When/Then form — then confirm it
   with the user in one turn ("here's what I'll build and what 'done' means — go,
   or adjust?"). This is a lightweight pass, not the full `varde-change plan`
   growth loop or AC-scoring machinery; for a large or uncertain change,
   recommend `varde-change plan` instead. Otherwise (no argument) discover
   ready plans per `references/build-plan-run.md`, which covers the
   `depends_on`-gating rule, and present them for the user to choose.

3. **Choose the execution location.** Use the current checkout by default, so
   the user can see the diff and interact while work proceeds. Stage only
   task-owned paths. Run
   `git check-ignore -q memory-bank/working/plans/<plan-id>/plan.md` once: if
   plan files are ignored they stay in the current checkout and never enter a
   commit; if tracked, they may move with a worktree and enter scoped commits.
   Isolate per `references/worktree.md` only when the user requests it or a
   concrete concurrent-edit risk makes the local checkout unsafe — state the
   reason first. That file's `created=` result decides who merges.

4. **Load the plan, decompose it, and state a posture** before starting
   implementation. See `references/build-plan-format.md` for plan/task file
   layout. **Select the posture** from the task's title, context, and
   `out_of_scope`, and load its file before that task's first tool call:

   | Posture | Select when | Reference |
   |---|---|---|
   | plan-execution | Default — the task carries no unusual risk profile | `references/build-posture-plan-execution.md` |
   | debug | A known bug or regression is the only goal | `references/build-posture-debug.md` |
   | fix | Several files and several independent verification checks make per-check checkpoints worthwhile | `references/build-posture-fix.md` |
   | refactor | Behavior-preserving restructuring, or `out_of_scope` forbids behavior change | `references/build-posture-refactor.md` |
   | spike | The goal is answering a design question rather than implementing it | `references/build-posture-spike.md` |

   State the chosen posture before implementing. A request to refactor a named
   target selects the refactor posture for the whole run; otherwise re-select
   per task.
   **Decompose the spec+AC into tasks:** load `references/build-decomposition.md`
   and break the plan's spec and plan-level acceptance criteria into
   `tasks/<task-id>.md` files (task-size check, sizing, edge-case slicing, and
   the doc-task decision live there). Acceptance criteria stay plan-level and are
   never re-authored per task; each task carries its own `#### Verification`
   block. Present the breakdown once and proceed when interactive; run straight
   through under `varde-change orchestrate` or an unattended named-plan run. Skip
   decomposition only when the plan already carries authored task files.

5. **Execute tasks one at a time, in dependency order, until none remain.**
   Derive the next ready task, execute it in the selected location, then
   re-derive. Delegate one task only when unfamiliar code, independent research,
   or a large bounded investigation makes a fresh context useful. Repeat until
   every remaining task is `done` or `blocked`. Full loop, resume check, and
   bounded-retry rules: `references/build-plan-run.md` and
   `references/build-execution.md`.

6. **Execute the selected task.** The executor loads
   `references/build-execution.md` in full before its first tool call. After
   implementation, run `varde-review simplify` scoped to the task's uncommitted
   changes, then run the task's `#### Verification` checks with bounded retry;
   on exhaustion, mark the task `blocked` and stop. Verify affected packages
   (`npx tsc --noEmit`, `npm test`) and run any project-configured lint,
   treating its findings as warnings. Commit the task's source changes, then set
   `status: done` and derive the next ready task. There is no integration stage.

7. **Write knowledge gotchas, if any.** Create or edit a markdown note in the
   repo's existing knowledge location (e.g. `memory-bank/knowledge/`) directly.
   Record path-level gotchas only when specific and useful, capped at four
   bullets. If it needs more, propose an architecture-level update instead.

8. **Hand off to review, verify plan-level AC, then complete.** Run one
   report-only review pass; if it produced findings, run one fix round then defer
   anything still open (no re-review loop). That fix round is invoked as
   `varde-review fix mode=build`, passing the review ID and `plan_context`. Under
   `mode=build` the fix pass attempts **every** finding rather than only the ones
   labelled `Label: auto-fix`, and creates no worktree of its own because this
   run owns the location — so dropping the parameter silently narrows what gets
   fixed. Then walk each `## Acceptance criteria` item in `plan.md`, verify it
   holds against the aggregate change, and toggle `- [ ]` to `- [x]` — an
   unconfirmable criterion is a blocker, not a silent pass. Complete the plan
   once every task is `done`, every criterion is confirmed, findings are
   resolved, and no companion action-item plan is pending. Full procedure:
   `references/build-plan-run.md` Section F, including the worktree Merge/Stop
   offer.

9. **Record lessons.** Invoke `varde-knowledge reflect`. If this run was
   **top-level** — not nested inside `varde-change orchestrate` — say so: the
   completed plan is a session boundary, so reflection records friction and
   useful knowledge *and* writes a handoff. If **nested**, scope it to friction
   and knowledge only; `varde-change orchestrate` writes the one boundary handoff
   when the whole feature completes.

## Gotchas

- Tasks are `tasks/<task-id>.md` files authored by this skill during
  decomposition (`references/build-decomposition.md`, template
  `assets/TASK-TEMPLATE.md`). Frontmatter
  `{type: task, parent: <plan-id>, status, depends_on, modifies: [], creates: []}`,
  plus optional `kind: research`; body `#### Out of scope`/`#### Verification`/
  `#### Progress`. Tasks carry **no** acceptance criteria — those are plan-level
  in `plan.md`; a task's own check is its `#### Verification`, and `status: done`
  means those checks passed.
- `change_files` is a legacy read-only alias some older plans still carry — treat
  it as data, never write it, and derive freshness from `modifies`/`creates`.
- Read a plan by reading its `plan.md` directly; enumerate tasks by globbing
  `tasks/*.md`. There is no `## Tasks` index and no generated `index.md`.
- A task-specific blocker marks that task `blocked` in its own file. A plan-wide
  blocker marks `plan.md` `blocked` and is the orchestrator's call.
- Ignored plan files stay local and never enter task commits. Tracked plan files
  follow the execution worktree and its scoped commits.

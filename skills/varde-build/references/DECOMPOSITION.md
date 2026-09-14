# Task decomposition

Build owns decomposition: given a settled spec + plan-level acceptance criteria
(`plan.md`, or the minimal plan synthesized for ad-hoc work — see `SKILL.md`'s
ad-hoc entry), break the work into task files under
`tasks/<task-id>.md` before execution. Acceptance criteria stay **plan-level**
and are never re-authored per task; a task's own gate is its `#### Verification`
block. Template: `assets/TASK-TEMPLATE.md`.

Run this once per plan run, after loading the plan and before deriving the first
ready task. For a plan authored by `/varde-plan`, scope signals were already
caught at plan time (`varde-plan/references/ACCEPTANCE-CRITERIA.md`); re-check
them here anyway, since ad-hoc work never passed through planning.

## Decide if a doc task is needed

Does the change introduce or meaningfully change an agent-visible feature or
workflow?
- **Feature** (new capability exposed to agents/users) → doc task writing
  `memory-bank/knowledge/reference/<slug>.md`
- **Flow** (multi-step agent/user workflow) → doc task writing
  `memory-bank/knowledge/flows/<slug>.md`
- If either: add a doc task depending on all implementation tasks. Its only
  output is an accurate, concise written Concept — no implementation narrative.
- Refactor-only or bug-fix with no agent-visible change → skip the doc task.

## Check for edge cases first

Read the matching pattern under "Edge cases" below only when its trigger fires:
- **Wide refactor**: if the goal names a shared symbol, type, or interface, read
  "Edge cases → Wide refactors" before decomposing. A mechanical rename/retype
  fanning across many independent packages needs expand → migrate → contract, not
  vertical slices. When `varde-code` is available (`references/VARDE-CODE-CLI.md`),
  run `symbol_blast_radius` on the symbol instead of guessing from package
  structure.
- **Native scan rule port**: if the work ports a native scan rule to TOML/SQL,
  read "Edge cases → Porting a native scan rule" first — native rules can read
  `entity.data` fields the persisted schema never populates; that gap must be its
  own upfront task.
- **Deletion**: if the work deletes a generated or intermediate artifact another
  task may read, read "Edge cases → Deletion tasks" first — structural edges miss
  textual consumers (a hardcoded fixture path, a `readFileSync` call).

## Build the breakdown

Draft the breakdown directly by default. Delegate only when unfamiliar code or
a large bounded investigation benefits from fresh context. Give the executor
the confirmed spec, plan-level acceptance criteria, prototype output if any,
and scope signals. Require per task:

- Observable outcome
- Expected files touched, if already known — otherwise say so and trust the
  executor to locate them via code_query/dependents, or `varde-code`'s
  `dependents`/`dependencies` when `varde-code` is available
- Dependencies
- Risks
- Verification: the `assert:`/`retrieve:` checks that prove this slice works
  (the task's own `#### Verification` block — not a copy of a plan-level AC)
- `test_approach`

Do not require a fixed step count or a named test function at authoring time —
those are mechanical details the executor works out. Over-specifying spends
tokens re-deriving what execution re-derives, and risks locking the executor into
a stale guess.

**Derive `test_approach`'s direction from what research found**, not a bare
command:
- Fragile/legacy code with no coverage → characterization tests first (pin
  current behavior, then change).
- Mostly config, packaging, or wiring → smoke test first (does it still
  start/build/load).
- State which direction and why in one line — a steer, not a full test plan.

## Research and design

- For tasks needing codebase research, investigate directly by default. Delegate
  a targeted question only when fresh context is useful. Let the executor read
  source and grep directly (the code-intelligence skill, or `varde-code`'s
  `get_symbol`/`dependents` when available, are optional aids).
  Convert findings into task `Context`, `Design notes`, or `Test approach`.
  Codebase-answerable unknowns must not become research tasks.
- For a task with a genuinely open interface decision — a real fork where
  multiple shapes are defensible, not a mechanical detail — run "Design It Twice"
  (`varde-plan/references/DESIGN-VOCABULARY.md`) before finalizing that task's
  `Design notes`. Skip it when the interface is dictated by an existing pattern or
  adjacent module.

## What good tasks look like

A task is the smallest execution-safe unit of code change — one testable outcome
an executor can implement from the generated briefing without making architecture
decisions. Check each task against this section in full before finalizing — the
fit gate (rewrite and re-gate automatically on failure), reject-shapes list, and
sizing heuristics.

**Reject these shapes:**
- A bucket named "wire everything"
- Unrelated behavior contracts in one task
- Tests can only pass after several later tasks
- Changes core behavior and multiple adapters together
- First failing test is unknown
- Files touched are mostly guesses
- Restates shared project docs instead of relying on injected context

**Sizing heuristics:**
- Start from outcomes, not file lists. Make an outcome inventory first, then
  group only outcomes that must ship together to remain testable.
- Optimize for the executor: constrain the problem, reduce ambiguity, make the
  first test obvious.
- Put only task-specific facts, file pointers, and verification details in the
  task — not shared terminology, standards, or architecture notes.
- CLI work: one subcommand behavior per task.
- Skills/docs: one workflow rule or decision surface per task.
- Prefer vertical slices through a public interface; use layer slices only when a
  foundation must exist before any public behavior can be tested.
- Resolve codebase unknowns before finalizing. Use a subagent only when fresh
  context materially helps. Use
  `kind: research` only for durable external outputs (decision record, prototype,
  reference doc) — `/varde-build` executes these as a research pass, not the TDD
  cycle, so the task body must name the output file.
- When `varde-code` is available (`references/VARDE-CODE-CLI.md`), check
  `hotspots` for a task's touched files — a task landing on a high
  complexity/churn file warrants a narrower slice and more fit-gate scrutiny.

**The fit gate.** Apply automatically to every task — rewrite and re-gate on
failure. The run always targets a Claude 5-class executor, so every task must
satisfy:

- **Spec-completeness** (spec gaps, not mechanical detail — an executor guesses
  wrong if left to fill them): one public behavior or workflow rule changes; no
  hidden architecture, product, or scope choice left for execution; verification
  is one command or a small named set (e.g. `npm test`, a named gate) — point at
  the check, don't script its steps; clean stop condition when done.
- **Mechanical detail, at executor granularity**: key coverage areas per
  plan-level acceptance criterion suffice in place of a named test function;
  expected files may be "known" as "the subsystem/module is identified," not a
  specific path or line; no required step count. Trust the executor's judgment on
  mechanics.

**Scope-consistency check.** Per task, check whether any design note describes a
schema/persistence change — new table, new column, new migration, "persist",
"backfill", or similar. If so, confirm the task body names the file(s) where that
schema lives (found by reading the relevant source or grepping — not by copying
another task's scope by analogy). If a task claims schema work but no schema file
is named, add it to the task body before writing.

## Present and record

- **Interactive build** (`/varde-build` no-arg, or `plan=<id>` run directly by
  the user): display the settled breakdown as an informational table, then pause
  once — "Here's the breakdown I'll execute — say now if any task is missing,
  wrong-scoped, or should be split differently." Wait one turn, then proceed.
- **Autopilot** (invoked by `/varde-orchestrate`, or a `plan=<id>` run the user
  has told to run unattended): skip the pause and proceed straight to execution.
- Author each task file from `assets/TASK-TEMPLATE.md` with populated `modifies`/
  `creates`, `depends_on`, `verified: pending`, and `status: backlog`. Task IDs
  are kebab-case with no date prefix; ensure uniqueness by globbing every plan's
  `tasks/*.md`. Author them in the selected execution location (`SKILL.md` step 3), then
  commit the initial task files once (`git add
  memory-bank/working/plans/<plan-id>/tasks/ && git commit -m "tasks: decompose
  <plan-id>"`) so a crashed run's resume gate finds them. Then hand the ordered
  list to the execution loop (`DISPATCH.md`) — readiness is computed live from
  `depends_on`, never stored.

## Edge cases

Narrow branches that don't apply to most work — read a subsection only when its
trigger under "Check for edge cases first" points here.

### Wide refactors

**Wide refactors are the exception to vertical slicing.** Default decomposition
assumes each task is an independently shippable vertical slice. A **wide
refactor** — one mechanical change (e.g. renaming a shared type) whose blast
radius fans across so many call sites that no single slice can land green —
breaks that assumption.

Check before decomposing:
- If the goal names a shared symbol, type, or interface, find its blast radius —
  search usages/dependents across the codebase (grep, or the code-intelligence
  skill) — before assuming a small footprint.
- Confirmed when the result fans across many independent packages/directories,
  not just a handful of related call sites.

When confirmed, decompose as **expand → migrate → contract**:
- One **expand** task: add the new form alongside the old; nothing breaks yet.
- N **migrate** tasks, batched by blast radius (per package/directory, using
  search results as batch boundaries) — each depends on expand. CI stays green
  batch to batch because the old form still exists.
- One **contract** task: delete the old form, depending on every migrate batch.
- If individual batches can't stay green alone, chain them through a shared
  integrate-and-verify task all batches depend into instead — green is only
  promised there.

### Porting a native scan rule to TOML/SQL

Requires a data-availability check before decomposition, not during. Native rules
can read `entity.data` fields nothing in the current schema populates (e.g. a
rule reading `entity.data.tokenFingerprint` or `entity.data.sourceModule` when no
indexer path writes it). A task scoped as "just port this rule to SQL" discovers
the gap only when the executor reads the native source mid-task, forcing a
mid-run stop.

Before decomposing any port of native rules:
- Read each rule's full implementation and list every `entity.data.<field>` (or
  equivalent custom field) it accesses.
- Check each field against the persisted schema by reading the db/schema module
  directly (e.g. `intelligence-db.ts`/`scan-types.ts`) — not by assuming it
  matches a sibling rule's data shape.
- Any field not actually persisted becomes its own upfront indexer task (data
  foundation first, rule port second, as a `depends_on` edge) — not an "adjust if
  needed" note inside the porting task.

### Deletion tasks

**Deletion tasks must track downstream textual consumers, not just structural
ones.** Before finalizing any task deleting a generated or intermediate artifact
(file, directory, or catalog other tasks may read), track every downstream
consumer — dependency edges based on shared source files miss a task whose notes
merely *read* the artifact, or a string-literal path a structural query can't
see.

Run all three checks — none subsumes the others:
- Grep every other draft task's body for the artifact's path; add `depends_on`
  for each match.
- Grep test files for hardcoded paths under any directory the task deletes (a
  fixture path, a snapshot path, a `readFileSync` call); note those test files as
  touched in the task body.
- For source paths, search for dependents/importers of each file under the
  deletion target (grep for import statements, or the code-intelligence skill) —
  catches non-textual consumers like a test importing a barrel file that
  re-exports the deleted module; add `depends_on` edges and note those files
  touched the same way.

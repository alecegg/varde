# Task decomposition

Given a settled spec plus plan-level acceptance criteria — `plan.md`, or the
minimal plan synthesized for ad-hoc work — break the work into `tasks/<task-id>.md`
files before execution. Template: `assets/TASK-TEMPLATE.md`. Acceptance criteria
stay **plan-level** and are never re-authored per task; a task's own check is its
`#### Verification` block.

Run once per plan run, after loading the plan and before deriving the first ready
task. A plan authored by `varde-change plan` already had its scope indicators
caught (`references/plan-acceptance-criteria.md`) — re-check anyway, since ad-hoc
work never passed through planning.

## Check the edge cases first

Three narrow branches need handling *before* decomposition, not during. Load
`references/build-edge-cases.md` when one fires, and only then:

- The goal names a shared symbol, type, or interface — a possible wide refactor.
  With `varde-code` available, run `symbol_blast_radius` rather than guessing
  from package structure.
- The work ports a native scan rule to TOML or SQL.
- The work deletes a generated or intermediate file another task may read.

## Decide whether a doc task is needed

A new agent-visible capability needs a doc task writing
`memory-bank/knowledge/reference/<slug>.md`; a new multi-step workflow needs one
writing `memory-bank/knowledge/flows/<slug>.md`. Either depends on all
implementation tasks, and its only output is an accurate, concise Concept — no
implementation narrative. Refactor-only or bug-fix work with no agent-visible
change skips it.

## Build the breakdown

Draft it directly by default; delegate only when unfamiliar code or a large
bounded investigation benefits from fresh context, giving that executor the
confirmed spec, plan-level acceptance criteria, any prototype output, and the
scope indicators.

Require per task: an observable outcome; expected files touched *if already
known* — otherwise say so and trust the executor to find them; dependencies;
risks; the `assert:`/`retrieve:` checks proving this slice works; and
`test_approach`.

Do **not** require a fixed step count or a named test function at authoring time.
The executor works those out, and over-specifying spends tokens re-deriving what
execution re-derives while risking a stale guess.

Derive `test_approach`'s **direction** from what research found, not a bare
command: fragile or legacy code with no coverage takes characterization tests
first (pin behaviour, then change); mostly config, packaging, or wiring takes a
smoke test first (does it still start, build, load). One line — a steer, not a
test plan.

## Research and design

Investigate directly by default; delegate a targeted question only when fresh
context helps. Convert findings into a task's `Context`, `Design notes`, or
`Test approach`. A codebase-answerable unknown must never become a research task.

For a genuinely open interface decision — a real fork where several shapes are
defensible, not a mechanical detail — run "Design It Twice"
(`references/plan-design-vocabulary.md`) before finalizing that task's
`Design notes`. Skip it when an existing pattern or adjacent module dictates the
interface.

## What good tasks look like

A task is the smallest execution-safe unit of code change: one testable outcome
an executor can implement without making architecture decisions. Check every task
against this whole section before finalizing.

**Reject these shapes:** a bucket named "wire everything"; unrelated behavior
contracts in one task; tests that can only pass after several later tasks; core
behavior and multiple adapters changing together; an unknown first failing test;
files touched that are mostly guesses; a restatement of shared project docs
instead of relying on injected context.

**Sizing heuristics:**

- Start from outcomes, not file lists. Inventory them, then group only those that
  must ship together to stay testable.
- Optimize for the executor: constrain the problem, reduce ambiguity, make the
  first test obvious.
- Keep only task-specific facts, file pointers, and verification details in the
  task — not shared terminology, standards, or architecture notes.
- CLI work: one subcommand behavior per task. Skills and docs: one workflow rule
  or decision per task.
- Prefer vertical slices through a public interface — a good slice is demoable
  or verifiable on its own. Use layer slices only when a foundation must exist
  before any public behavior can be tested.
- Resolve codebase unknowns before finalizing. Reserve `kind: research` for
  lasting external outputs — a decision record, prototype, reference doc — which
  build runs as a research pass rather than the TDD cycle, so the task body must
  name the output file.
- With `varde-code` available, check `hotspots`: a task landing on a high
  complexity or churn file warrants a narrower slice and more scrutiny.

**The task-size check:** Apply to every task; rewrite and re-check on failure.
The run targets a Claude 5-class executor, so each task must have exactly one
public behavior or workflow rule changing, no hidden architecture, product, or
scope choice left for execution, verification that is one command or a small
named set (point at the check, don't script its steps), and a clean stop
condition. At executor granularity, key coverage areas per plan-level acceptance
criterion stand in for a named test function, "the subsystem is identified"
stands in for a specific path, and no step count is required.

**Scope-consistency check:** Per task, check whether a design note describes a
schema or persistence change — a new table, column, or migration, or words like
"persist" or "backfill". If so, confirm the task body names the file(s) where
that schema lives, found by reading the source or grepping, never by copying
another task's scope by analogy.

## Present and record

A user steering the build directly gets the settled breakdown as an informational
table and one pause: "Here's the breakdown I'll execute — say now if any task is
missing, wrong-scoped, or should be split differently." Wait one turn, then
proceed. An unattended run skips the pause.

Author each task from `assets/TASK-TEMPLATE.md` with populated `modifies`,
`creates`, `depends_on`, and `status: backlog`. Task IDs are
kebab-case with no date prefix; ensure uniqueness by globbing every plan's
`tasks/*.md`. Author them in the selected execution location, then commit the
initial task files once so a crashed run's resume check finds them. Hand the
ordered list to `references/build-dispatch.md` — readiness is computed live from
`depends_on`, never stored.

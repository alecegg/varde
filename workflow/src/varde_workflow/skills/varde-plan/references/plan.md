# Plan

## Start

`<working>/plans/<date>-<slug>/plan.md` exists after the first turn, written from `assets/PLAN-TEMPLATE.md` with `title` set to the prompt and `group` set.
Write `label` last, from the finished Problem and Solution (3-5 words, at most
36 characters; no dates, versions, or plan ids; unique among open plans).

Seed best guesses at once in the template's formats: Given/When/Then
criteria, and every unknown as an Open Question or Assumption.

## First turn

- Research the prompt against the repo.
- List deferred review findings located in the plan's scope as Open Questions; the user decides include or defer.
- Give the user the plan path, say they may edit it directly, and ask one question.

## The growth loop

Let the repo answer what it can each turn. Load `references/varde-code-cli.md` once, at the first growth-loop turn. Check scope and dependents; do not assume them.

Route every unknown instead of blocking; impact beats confidence:

- Research it when code or search can answer, or when a `[needs prototype]` run can.
- Assume it when a wrong guess stays inside one Design subsection: add
  `## Assumptions` with `confidence: high` or `medium`.
- Ask it otherwise (low confidence, or touching the plan split, AC, an external
  contract, or solution shape): add `## Open Questions` with a recommendation.

Land every answer in the plan: update Design (or Non-goals/Constraints), add
`<question> → <answer>` to `## Decisions so far`, and remove the resolved line.
A user edit to Open Questions, Assumptions, Design, Non-goals, or
Constraints counts as an answer. When launched by an orchestrator, send each open
question and options to the orchestrator slot as `--kind needs-user`, with
`plan_id` and exact `question` in notes.

## Knowledge and interfaces

Link applicable specs, decisions, and definitions in `<knowledge>/` under
`## Related` and use their vocabulary. Raise a stale one as a single
Open Question. For a touched surface (exported API, CLI flag,
env var, CI config, shared type, or a file others read), record consumers
in Design and AC.

## Acceptance criteria

Criteria are plan-level (true after ship, however build slices it), and each
names a command or a file a reader judges.

- **`assert:`** (preferred): a command, grep, or test whose pass/fail needs no
  LLM judgment.
- **`retrieve:`**: the file(s) or grep an LLM reads and judges, and what it
  looks for. Restate it as `assert:` when a command, exit code, file existence,
  or non-empty output can decide it.

## Exit outcome

Finalize when all three hold:

- Open Questions has no live item.
- Every criterion is testable as written.
- Every assumption is user-confirmed, in chat or in the plan.

## Finalize

The plan is final when all of these hold:

- `varde plan validate <plan.md> --json` has no diagnostics.
- Tasks exist per `references/plan-decomposition.md`.
- Several independently shippable changes become a plan set only after the user agrees to the split; each plan is merged separately with user approval.
- `varde learn check <plan.md> <task.md>...` has no errors; warnings are left unfixed.
- Planned data and screens are `ui` components (`varde learn docs blocks`), and `varde learn check <plan.md>` passes.
- One independent report-only review is written to `<plan-dir>/notes/plan-review.md`.
  It covers splits, wave independence, assumptions, human choices, criteria,
  shippability, and scope worth keeping.
- Its findings are applied except cuts, and a fixes-only re-check follows.
- No scope is removed or deferred without the user: each recommended cut is a
  question with its reason and options (keep, change approach, cut).
- The user has answered the final completeness check ("Anything left to resolve
  before we finalize?"), changes are applied, and one fixes-only re-check ran.
- The plan frontmatter records `reviewed_commit: <target repository HEAD the
  plan review read>` and `reviewed_on: <YYYY-MM-DD>`; Finalize creates no worktree.
- No content changes follow; the plan stays `backlog` until build moves it to
  `active`. Announce `Plan <plan-id> is ready; ask to build it.`

## Asking questions

Format: `<Question>`, then numbered options with
`Other - describe what you want`, and a `Recommendation: <n> (<label>) - <reason>`.

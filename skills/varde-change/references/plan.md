# Plan

## Start or resume

Create `<working>/plans/<date>-<slug>/` on the first turn and write `plan.md`
there from `assets/PLAN-TEMPLATE.md`, with `title` set to the prompt; rename by
hand only when scope changes a lot.

Resume by searching `<working>/plans/` for a `plan.md` with `status: backlog`
and a live Open Questions bullet: one, resume it; several, list them as
`title - path` and ask which; none, wait for the idea.

Seed best guesses in the template's formats immediately: Given/When/Then
criteria, and every unknown as an Open Question or Assumption.

## First turn

- Research the prompt with `varde map context_pack` (topic query; see its `--help`).
- Scan `<working>/reviews/deferred/` for findings located in the plan's scope;
  list each as an Open Question with a blank Disposition, review date, and
  deduplicated Source and id; the user decides include or defer.
- Tell the user the plan path and welcome direct edits, then ask one question
  and wait.

## The growth loop

Research what the repo can answer each turn; load
`references/varde-code-cli.md` once, at the first growth-loop turn. Check scope and
dependents with `varde`; do not assume them.

Route every unknown instead of blocking; impact beats confidence:

- Research it when code or search can answer, or when a `[needs prototype]`
  run can (load `varde-prototype`: use your skill tool, or read
  `../../varde-prototype/SKILL.md`).
- Assume it when a wrong guess stays inside one Design subsection: add
  `## Assumptions` with `confidence: high` or `medium`.
- Ask it otherwise (low confidence, or touching the plan split, AC, an external
  contract, or solution shape): add `## Open Questions` with a recommendation.

Write each resolved item into its `## Design` subsection (or
Non-goals/Constraints), append `<question> → <answer>` to
`## Decisions so far`, and remove the resolved line.

A user edit to Open Questions, Assumptions, Design, Non-goals, or Constraints
counts as an answer; process it with the chat message.

## Knowledge and interfaces

Search `<knowledge>/` for specs, decisions, and definitions that apply; link
them under `## Related` and use their vocabulary, raising a stale one as a
single Open Question.

For a touched surface with consumers (exported API, CLI flag, env var, CI
config, shared type, or a file others read), find them with
`varde map blast_radius` (or `nav_map`/`clusters` when useful) and record
them in Design and AC.

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

1. Run `varde plan validate <plan.md> --json` and fix diagnostics.
2. Decompose into tasks per `references/plan-decomposition.md`; use a plan set
   for several independently shippable changes
   ([below](#split-into-a-plan-set)).
3. Run `varde doc lint` on the plan and its tasks. Fix errors and leave warnings unfixed.
4. Give an independent reviewer the plan, tasks, lint warnings, and resolved
   `<working>`/`<knowledge>` paths; ask for one report-only round over splits,
   wave independence, assumptions, human choices, criteria, shippability, and
   scope worth keeping, written to `<plan-dir>/notes/plan-review.md`; apply the
   findings except cuts, ask the user about cuts, then request one fixes-only
   re-check. Include in the brief each task's origin (user request or friction
   id, named by the planner) and:
   - Do not remove or defer scope; record each recommended cut as a question
     with its reason and options (keep, change approach, cut). For user-requested
     work, judge usefulness, cost, and alternatives including doing nothing,
     and never cut for missing friction evidence; for friction-derived work,
     friction evidence is the main backing.
5. Ask the final completeness check: group unseen assumptions and changes by
   impact, one line each, and ask "Anything left to resolve before we
   finalize?" Apply changes and run one fixes-only re-check.
6. After confirmation, record `reviewed_commit: <target repository HEAD the
   plan review read>` and `reviewed_on: <YYYY-MM-DD>` in the plan frontmatter;
   Finalize creates no worktree.
7. Make no more content changes; the plan stays `backlog` until build moves it
   to `active`. Announce `Plan <plan-id> is ready; ask to build it.`

## Split into a plan set

Use this at Finalize step 2 when review finds several independently shippable
changes. A plan set is a folder of plans that `varde plan status` shows
together, ordered by plan-level `depends_on`; each plan is reviewed and merged
on its own with user approval.

1. List candidate titles and dependency order; ask whether any should be
   combined or split differently, then wait.
2. Create the set as a folder under `<working>/plans/`, each plan at
   `<set>/<slug>/plan.md` and finalized with the steps above.
3. Delete the parent's task files and set its status to `cancelled`.

## Asking questions

Format: `<Question>`, then numbered options with
`Other - describe what you want`, and a `Recommendation: <n> (<label>) - <reason>`.

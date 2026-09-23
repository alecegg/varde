# Start a plan

Planning creates one evolving `plan.md`.
It defines scope, design, and acceptance criteria.
It never creates task files.

## First turn

Do not load other planning references this turn.
Batch repository discovery into one read-only call.
When `varde-code` exists, combine its index build and
`varde-code context_pack` within that call.
Use the feature terms as its query.
Prefer its scoped result over broad reads or greps.
Fall back when unavailable or unsuccessful.

1. Work in the current checkout by default. Isolate only when requested, when
   a caller owns a worktree, or when concurrent edits risk collision. Before
   isolation, probe whether plan files are ignored. Ignored plans must stay
   within the caller checkout. Read `references/worktree.md` only before
   isolation. In-document collaboration uses the stable plan path. Read
   `references/varde-workflow-cli.md` only when that mode applies. Stop before
   creating plans when `varde-workflow` is unavailable.
2. Form `<UTC-date>-<slug>-draft`. Check collisions immediately. Append a
   numeric suffix when needed. Create
   `<working>/plans/<plan-id>/plan.md`.
3. Use frontmatter fields `status: backlog`, `title`, and `type: plan`.
   Add Problem, Solution, Non-goals, Constraints, Design, Decisions so far,
   Open Questions, Assumptions, and Acceptance criteria. Never add Tasks.
4. Seed genuine best guesses immediately. Keep Problem and Solution concise.
   Use structured bullets elsewhere. Write Given, When, Then criteria with
   assert or retrieve evidence. Format unknowns as recommended questions.
   Format assumptions with affected area and confidence.
5. Tell the user the plan path. Welcome direct edits. Ask one highest-value
   question as three numbered options. Include Other and one recommendation.
   Then wait before doing further planning.

A readiness question follows this same flow.
It may stop once readiness sections answer the question.

## Later turns

After the first answer, read `references/plan-grow-doc.md`.
Follow its per-turn loop until its exit criteria pass.
Write every resolved decision immediately.
Ask one question per turn.
Research repository-answerable questions instead of asking them.
When `varde-code` is available, read `references/varde-code.md` before using
its planning operations.

During scope decisions, inspect deferred action-item review findings.
Show relevant findings with review date and staleness context.
Let the user include or defer them.
Never add findings automatically.

After growth completes, follow its referenced fundamentals check.
Then read `references/plan-authoring.md` and
`references/plan-acceptance-criteria.md` for finalization.
Check specification consistency and judgment calls.
Mark the plan ready without creating tasks.

If tracked plan isolation was created, offer merging and cleanup.
Finally invoke `varde-knowledge reflect` without a handoff.

## Rules

- Write each decision when made.
- Use inline numbered questions, never native question tools.
- Continue automatically after completeness confirmation.
- Stop for failed tools or confirmed contradictions.
- Produce exactly one file named `plan.md`.
- Keep plan-level acceptance criteria inside that file.

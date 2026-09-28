# Start a plan

Planning grows one `plan.md` defining scope, design, and acceptance criteria.
It never creates task files.

## First turn

Of the planning references, load only `interview.md` this turn (plus
`worktree.md` if step 1 routes there). Batch discovery into
one read-only call; include `varde-code context_pack` (feature terms) when
available.

1. Work in the current checkout. Isolate only when requested, when a caller
   owns a worktree, or when concurrent edits risk collision — then probe
   whether plan files are ignored first (ignored plans stay in the caller
   checkout) and read `references/worktree.md`.
2. Form `<UTC-date>-<slug>-draft` from `date -u +%Y-%m-%d` and a temporary slug
   from the prompt. Before creating it, append `-2`, `-3` if the id exists;
   keep the id until finalization. Create
   `<working>/plans/<plan-id>/plan.md` from `assets/PLAN-TEMPLATE.md` with
   Write/Edit, `title` set to the initial prompt.
3. Seed genuine best guesses immediately, in the template's formats, including
   Given/When/Then criteria and every unknown as an Open Question or
   Assumption.
4. Tell the user the plan path and welcome direct edits. Ask the one
   highest-value question per `references/interview.md`, then wait.

## Later turns

Follow plan-grow-doc every turn until its exit criteria pass, then
plan-fundamentals Finalize.

During scope decisions, list every blank-`Disposition` finding in
`<working>/reviews/deferred/` whose `Location` falls in this plan's scope,
whether or not it has an `Escalated:` note. Also list scoped blank findings
with an `Escalated:` note in other `<working>/reviews/` and nested plan reviews
(`<working>/plans/*/<review-id>/`). Include review date
and deduplicate copied findings by `Source` and original ID. The user includes
or defers each; never add one automatically.

If tracked plan isolation was created, offer merging and cleanup after
finalizing.

Finally, record real obstacles through `varde-learn` and durable decisions
through `varde-knowledge`; otherwise skip.

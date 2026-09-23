# Resume planning (empty invocation)

When invoked with no feature idea:

- **Find drafts.** Use `references/plan-recipes.md`'s "Find draft plans to
  resume" section. Run its grep command and apply its `type: plan` filter.
- **Include nested plans.** Include every draft plan, regardless of nesting
  depth. This includes stub child plans from `references/plan-splitting.md`.
  Their compound ids (`<group-plan-id>/<child-plan-id>`) resolve like any other
  plan id because they are directory paths. Do not special-case children.
- **Present and ask.** Present the full result set as a numbered list of title
  and plan id. Read the `title` frontmatter field from each match. Do not show a
  body snippet or silently limit the list to "most recent." Ask which plan to
  resume. If the result is empty, start a new session only after the user gives
  an idea.
- **Resume.** Read `<working>/plans/<plan_id>/plan.md`. Continue from
  the headings that still contain placeholder text.

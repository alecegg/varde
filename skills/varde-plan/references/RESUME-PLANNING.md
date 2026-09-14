# Resume planning (empty invocation)

When invoked with no feature idea:

- **Find drafts.** See `references/RECIPES.md` ("Find draft plans to resume") for
  the grep command and `type: plan` filter.
- **Include nested plans.** The search surfaces every draft plan regardless of
  nesting depth — including stub child plans from `references/PLAN-SPLITTING.md`,
  whose compound ids (`<group-plan-id>/<child-plan-id>`) resolve the same way as
  any other plan id (their directory path). No special-casing for children.
- **Present and ask.** Present the full result set as a numbered list of title +
  plan id (read the `title` frontmatter field from each match) — do not display
  the body snippet, and do not silently narrow to "most recent." Ask which to
  resume. An empty result starts a new session only after the user supplies an
  idea.
- **Resume.** Read the draft's `memory-bank/working/plans/<plan_id>/plan.md` and
  determine where to continue from which headings still contain placeholder text.

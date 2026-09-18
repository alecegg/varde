# Plan finalization

## Finalize the acceptance criteria

Run the acceptance-criteria review over the full criteria set before finalizing:
testability scoring, GWT compliance, assert/retrieve tagging, and the scope
signals — full procedure in `references/plan-acceptance-criteria.md`. Apply the
reviewed criteria to `plan.md`'s `## Acceptance criteria` section with a targeted
edit.

Search prior plans and knowledge docs (grep/glob over
`memory-bank/working/plans/` and `memory-bank/knowledge/`) for matching decision
files or plan IDs to build a `related:` list.

## In-flow consistency check

Before finalizing, confirm `## Open Questions` is empty (or every line is
explicitly `n/a`) — the final completeness check in `references/plan-fundamentals.md`
Step 4 should already guarantee this. Re-check because the later AC review
can show a gap the earlier pass missed (see the re-scan-for-gaps rule in
`references/plan-fundamentals.md`). Then review `plan.md` for internal
consistency:

- Do the acceptance criteria still match the confirmed spec, and is each one
  testable and in Given/When/Then form?
- Does every scope indicator caught during planning
  (`references/plan-acceptance-criteria.md`) show up in the spec/AC, so build won't
  discover it mid-decomposition?
- Do `Design`/`Decisions so far`/`Open Questions`/`Assumptions` follow
  `assets/PLAN-TEMPLATE.md`'s writing-style rule (structured bullets/signatures,
  not prose paragraphs — `Problem`/`Solution` are the only sections allowed to
  stay prose)?

Prefix anything questionable with `⚠`. This is a review pass — it doesn't rewrite
on its own, but reformat any prose-drifted section directly instead of just
flagging it.

## Mark the plan ready

Targeted edit to `plan.md` frontmatter: set `status: backlog` and add `related:`.

## Taste decisions check

The automatic phase resolves close calls without the user seeing them. Before finalizing,
list the genuine judgment calls made after the user confirmed the plan. A Design It Twice
interface pick and why alternatives lost, an AC rewrite that changed what a
criterion asserts (not just its format), a single-vs-split plan boundary call, a
defensible-either-way scope call. Skip mechanical ones (naming, a template fill) —
this is for calls a reasonable person could've made differently, not a full
changelog.

Present the list and ask: "These are the judgment calls made without stopping to
ask — finalize as-is, or is anything here worth revisiting first?" If there were
no close calls, say so plainly. Wait for the answer before
finalizing. If the user wants a change, apply it and re-run the consistency check
above before asking again.

## Finish and prompt

Recheck the plan path with `git check-ignore -q`. If ignored, keep the complete
plan directory local and uncommitted. If tracked, stage and commit that plan
directory alone. Tell the
user: "Plan `<plan-id>` is ready — ask to build it and it will be decomposed
into tasks and executed."

# Plan finalization

## Finalize the acceptance criteria

Before finalizing, review every acceptance criterion for testability, GWT
compliance, assert/retrieve tagging, and scope signals. Use the full procedure
in `references/plan-acceptance-criteria.md`. Apply the reviewed criteria to
`plan.md`'s `## Acceptance criteria` section with a targeted edit.

Search prior plans and knowledge docs with grep/glob over
`<working>/plans/` and `<knowledge>/`. Add matching decision
files or plan IDs to a `related:` list.

## Check consistency before finalizing

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

Prefix anything questionable with `⚠`. Do not only flag prose drift. Reformat
each prose-drifted section directly during this pass.

## Mark the plan ready

The plan starts in `backlog`, the schema's initial state. Marking it ready does
not change that state. `varde-change build` moves it to `active` when the run
starts. Confirm that the artifact is well-formed and record its links with:

```bash
varde-workflow validate <plan-dir>/plan.md --json
```

Fix any diagnostic it reports, then apply a targeted edit adding `related:`.
This is ordinary frontmatter that the state machine does not own. Without the
CLI, skip validation and edit `related:` directly
(`references/varde-workflow-cli.md`).

## Taste decisions check

The automatic phase resolves close calls without showing them to the user.
Before finalizing, list the genuine judgment calls made after the user confirmed
the plan. Include a Design It Twice interface choice and why alternatives lost,
an AC rewrite that changed what a criterion asserts (not only its format), a
single-vs-split plan boundary, or a defensible scope choice. Skip mechanical
choices such as naming or filling a template. This list records choices a
reasonable person could have made differently, not the full changelog.

Present the list and ask: "These are the judgment calls made without stopping to
ask — finalize as-is, or is anything here worth revisiting first?" If there are
no close calls, say so plainly. Wait for the answer before finalizing. If the
user wants a change, apply it and re-run the consistency check above before
asking again.

## Finish and prompt

Recheck the plan path with `git check-ignore -q`. If ignored, keep the complete
plan directory local and uncommitted. If tracked, stage and commit only that
plan directory. Tell the user: "Plan `<plan-id>` is ready — ask to build it and
it will be decomposed into tasks and executed."

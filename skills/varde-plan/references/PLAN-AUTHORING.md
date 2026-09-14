# Plan finalization

The plan produces one artifact: `plan.md`, carrying the spec and the plan-level
`## Acceptance criteria`. It authors **no** task files (`/varde-build` creates
them at build time). `plan.md` has no `## Tasks` section and no `tasks:`
frontmatter array.

## Finalize the acceptance criteria

Run the acceptance-criteria review over the full criteria set before committing:
testability scoring, GWT compliance, assert/retrieve tagging, and the scope
signals — full procedure in `references/ACCEPTANCE-CRITERIA.md`. Apply the
reviewed criteria to `plan.md`'s `## Acceptance criteria` section with a targeted
edit.

Search prior plans and knowledge docs (grep/glob over
`memory-bank/working/plans/` and `memory-bank/knowledge/`) for matching decision
files or plan IDs to build a `related:` list.

## In-flow consistency check

Before committing, confirm `## Open Questions` is empty (or every line is
explicitly `n/a`) — the completeness gate in `references/PLAN-FUNDAMENTALS.md`
Step 4 should already guarantee this, but re-check since autopilot's AC review
can surface a gap the earlier pass missed (see the re-scan-for-gaps rule in
`references/PLAN-FUNDAMENTALS.md`). Then review `plan.md` for internal
consistency:

- Do the acceptance criteria still match the confirmed spec, and is each one
  testable and in Given/When/Then form?
- Does every scope signal caught during planning
  (`references/ACCEPTANCE-CRITERIA.md`) show up in the spec/AC, so build won't
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
There is no `## Tasks` list to fill and no per-task status to promote.

## Taste decisions gate

Autopilot resolves close calls without the user seeing them. Before committing,
compile the genuine judgment calls made during autopilot — a Design It Twice
interface pick and why alternatives lost, an AC rewrite that changed what a
criterion asserts (not just its format), a single-vs-split plan boundary call, a
defensible-either-way scope call. Skip mechanical ones (naming, a template fill) —
this is for calls a reasonable person could've made differently, not a full
changelog.

Present the list (or state plainly that autopilot made no close calls this run)
and ask: "These are the judgment calls made without stopping to ask — commit
as-is, or is anything here worth revisiting first?" Wait for the answer before
committing. If the user wants a change, apply it and re-run the consistency check
above before asking again.

## Commit and prompt

After the consistency check, stage only this plan's own directory and any updated
knowledge files — never `git add memory-bank/working/plans/` broadly, since a
concurrent session's in-progress files under a sibling plan directory would get
swept in:
```bash
git add memory-bank/working/plans/<plan-id>/ memory-bank/knowledge/
git commit -m "plan(<plan-id>): add <plan title>"
```

Tell the user: "Plan `<plan-id>` committed. Run `/varde-build plan=<plan-id>` to
decompose it into tasks and execute."

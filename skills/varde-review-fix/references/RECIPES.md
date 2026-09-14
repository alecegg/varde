# review-fix — recipes

Curated, guardrailed call shapes for this skill's common operations. Use
these on the happy path.

This skill reads and updates review markdown files directly — there is no
core operation for scope selection or disposition updates. It has no
database-backed finding workflow: everything below is plain shell and
file-editing.

## Confirm a clean working tree before touching a review folder

See `SKILL.md` step 2 for the `git status --porcelain` check and fail-fast
message.

## Read the scope

1. Resolve `review_dir` from the invocation or the latest review folder.
2. Read generated nav-only `index.md`, the review concept `review.md`, and
   the listed category files.
3. Parse level-two finding headings and the required bold fields.
4. Count findings by label and disposition.

Read `references/TRIAGE-PASS.md` for parsing and ordering rules.

## Per-finding stash isolation

```bash
git stash -u
```

Run before applying a finding's selected solution. On verification failure:

```bash
git stash pop
```

On verification success:

```bash
git stash drop
```

Stash isolation is per-finding — never batch stashes across findings. Then
run the repository verification commands (type checker, tests, and any
task-defined `assert:` lines).

## Apply changes to a finding block

Use the normal file editing tools to update only the selected finding block.
Preserve the heading, severity, label, location, summary, and solutions.
Change only `Disposition` (and add a decision note when needed).

Read `references/TRIAGE-PASS.md` for the required ordering and field rules,
`references/FIX-PASS.md` for the automated pass and escalation gate, and
`references/COMPANION-PLAN.md` for companion-plan creation. Use `/varde-build`
for focused fixes and companion plan tasks.

## Simplify pass over applied fixes

After the automated and human triage passes, if any finding was applied and
left uncommitted changes, invoke `simplify` scoped to those changes (working
tree/staged diff). Skip silently if no finding was applied — this is not a
general-purpose cleanup pass, only a scoped follow-up on what the fix pass
just touched.

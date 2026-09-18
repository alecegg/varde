# review-fix — recipes

This skill reads and updates review markdown files directly with shell
commands and file edits. There is no findings database and no write operation
for scope selection or disposition updates.

## Confirm a clean working tree before touching a review folder

See `references/fix.md` step 2 for the `git status --porcelain` check and fail-fast
message.

## Read the scope

1. Resolve `review_dir` from the invocation or the latest review folder.
2. Read generated nav-only `index.md`, the review concept `review.md`, and
   the listed category files.
3. Parse level-two finding headings and the required bold fields.
4. Count findings by label and disposition.

Read `references/fix-triage-pass.md` for parsing and ordering rules.

## Per-finding diff isolation

Record the working-tree diff before applying a finding's selected solution, so a
failure can be reverted to exactly that point:

```bash
git diff > "$TMPDIR/pre-finding.diff"
```

On verification failure, revert only this finding's own changes and leave every
prior successful fix in place. Isolation is per-finding — a whole-tree `git stash`
would take the earlier fixes with it. Then run the repository verification
commands (type checker, tests, and any task-defined `assert:` lines).

## Apply changes to a finding block

Use the normal file editing tools to update only the selected finding block.
Preserve the heading, severity, label, location, summary, and solutions.
Change only `Disposition` (and add a decision note when needed).

Read `references/fix-triage-pass.md` for the required ordering and field rules,
`references/fix-pass.md` for the automated pass and escalation gate, and
`references/fix-companion-plan.md` for companion-plan creation. Use `varde-change build`
for focused fixes and companion plan tasks.

## Simplify pass over applied fixes

After the automated and human triage passes, if any finding was applied and
left uncommitted changes, invoke `simplify` scoped to those changes (working
tree/staged diff). Skip silently if no finding was applied — this is not a
general-purpose cleanup pass, only a scoped follow-up on what the fix pass
just touched.

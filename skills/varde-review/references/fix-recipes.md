# review-fix recipes

Read and update review Markdown files directly with shell commands or file
edits. This skill has no findings database or separate write operation for
scope selection and disposition updates.

## Confirm a clean working tree before touching a review folder

See step 2 of `references/fix.md` for the
`git status --porcelain` check and fail-fast message.

## Read the scope

1. Resolve `review_dir` from the invocation or the latest review folder.
2. Read generated nav-only `index.md`, the review concept `review.md`, and
   the listed category files.
3. Parse level-two finding headings and the required bold fields.
4. Count findings by label and disposition.

Read `references/fix-triage-pass.md` for parsing and ordering rules.

## Per-finding diff isolation

Record the working-tree diff before applying a finding's selected solution. If
verification fails, restore the diff to that point:

```bash
git diff > "$TMPDIR/pre-finding.diff"
```

On verification failure, revert only this finding's changes. Leave every prior
successful fix in place. Isolation is per finding. A whole-tree `git stash`
would also remove earlier fixes. Then run the repository verification commands:
the type checker, tests, and any task-defined `assert:` lines.

## Apply changes to a finding block

Use the normal file editing tools. Update only the selected finding block.
Preserve the heading, severity, label, location, summary, and solutions.
Change only `Disposition` (and add a decision note when needed).

Read `references/fix-triage-pass.md` for ordering and field rules,
`references/fix-pass.md` for the automated pass and escalation gate, and
`references/fix-companion-plan.md` for companion-plan creation. Use
`varde-change build` for focused fixes and companion plan tasks.

## Simplify pass over applied fixes

After the automated and human triage passes, check for applied findings with
uncommitted changes. If any exist, invoke `simplify` on those changes in the
working tree or staged diff. Skip silently when no finding was applied. This is
a scoped follow-up on the fix pass, not general cleanup.

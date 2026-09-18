# review — recipes

Use these commands and direct file reads or writes. No external tool server is
needed.

## Route changed files before category review

```bash
git diff --name-only <base>...HEAD
```

Fall back to `git diff --name-only HEAD -- <section>` when scoping to one
section. Read the resulting file list and use judgment to separate files that
need review from generated files, lockfiles, and vendored code. Delegate only
when one bounded section exceeds available context.

Everything else this pass does — analyzing changed code, creating the review
folder, writing findings, and searching project knowledge before each one — is
procedure, and `references/report-workflow.md` owns it end to end. Its section
names match `references/report.md`'s workflow steps. Finding and folder layouts
live in `references/report-format.md`.

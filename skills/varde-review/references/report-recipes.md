# review — recipes

Use these commands and direct file reads or writes. No external tool server
is needed.

## Route changed files before category review

```bash
git diff --name-only <base>...HEAD
```

Fall back to `git diff --name-only HEAD -- <section>` when scoping to one
section. Read the resulting file list. Use judgment to separate files that
need review from generated files, lockfiles, and vendored code. Delegate only
when one bounded section exceeds available context.

Follow `references/report.md` for the remaining procedure. It covers analyzing
changed code, creating the review folder, writing findings, and searching
project knowledge before each finding. Each workflow step names its detailed
section. Use `references/report-format.md` for finding and folder layouts.

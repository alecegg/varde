# review — recipes

Curated procedures for this skill's common operations, using plain shell
commands and direct file reads/writes — no external tool server is required.

## Route changed files before category review

```bash
git diff --name-only <base>...HEAD
```

Fall back to `git diff --name-only HEAD -- <section>` when scoping to one
section. Read the resulting file list and use judgment to separate files that
need review from generated files, lockfiles, and vendored code. Delegate only
when one bounded section exceeds available context.

## Analyze changed code

See the `## Analyze the changed code` section of `references/WORKFLOW.md`.

## Creating the review folder — direct markdown authoring

See the `## Create the review folder` section of `references/WORKFLOW.md` and
the `## Review folder layout` section of `references/FORMAT.md`.

## Writing findings — direct markdown authoring

See the `## Review each changed section` section of
`references/WORKFLOW.md` and the `## Finding format` section of
`references/FORMAT.md`.

## Searching project knowledge before each finding

See step 6 of the `## Review each changed section` section of
`references/WORKFLOW.md`.

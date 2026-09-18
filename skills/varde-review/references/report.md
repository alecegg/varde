# Report mode

## Choose the breadth

| The request is | Categories |
|---|---|
| A plain review, with no stated breadth | The default three: `CORRECTNESS`, `CODE`, `ARCHITECTURE` |
| A thorough or full review | All 10, filtered by relevance |
| A named concern — security, performance, tests, and so on | That single category |

If the user names a keyword, path, or area, filter the detected sections to it.
State the resolved breadth and the active category list before proceeding.

## Choose the target

| The tree is | Review |
|---|---|
| Dirty — uncommitted or staged changes | Those changes, against `HEAD` |
| A branch, range, or PR named by the user | Exactly what they named |
| Clean, with no base named | Commits since the last merge or tag — `git describe --tags --abbrev=0` or `git log --merges -n1 --format=%H`, whichever is nearer `HEAD` |

Say which target you resolved and how, before reading any code. On the third
row, also offer the whole-codebase pass in the same message: "review this repo"
means the recent batch to one reader and every file to another, and guessing
silently makes two runs of the same request review different code.

## Workflow

1. **Load the instructions.** Read `references/report-recipes.md` for common
   commands. Load `references/varde-code.md` if that CLI is on PATH, for
   commands that add call-graph and structure details to step 4.
2. **Resolve the spec source.** When `CORRECTNESS` is active, resolve the
   correctness spec source. Full procedure: the `## Resolve mode and spec
   source` section of `references/report-workflow.md`.
3. **Create the review folder.** Create it before reviewing categories.
   Use its `reviewDir` for all later files. Full
   procedure: the `## Create the review folder` section of
   `references/report-workflow.md`.
4. **Analyze the changed code.** Read the diff and changed files directly,
   run the project's own lint/test/typecheck commands if any exist, and grep
   for known anti-patterns. Write findings straight into the review folder.
   Full procedure: the `## Analyze the changed code` section of
   `references/report-workflow.md`.
5. **Detect sections.** Load the configured sections or auto-detect them,
   then narrow to the area the user named, if any. Full procedure: the `## Detect sections`
   section of `references/report-workflow.md`.
6. **Review each changed section.** Check all active categories while
   reading each section. Full procedure: the `## Review each changed section`
   section of `references/report-workflow.md`.
7. **Count and report.** Count the findings, confirm the review
   folder is complete, and report results to the user. Full procedure: the
   `## Roll up and report` section of `references/report-workflow.md`.
8. **Record lessons.** Invoke `varde-knowledge reflect`, scoped to this run. It
   records friction and durable lessons only — a handoff belongs at a
   session boundary, which this is not.

Report only — do not modify source files. If a step fails outright, report a
hard error and stop.

## Gotchas

- Use a subagent only for a section exceeding available context. Give it a
  refute mandate and verify its `high`/`critical` candidates before persisting.
  Full wording: `## Review each changed section` in `references/report-workflow.md`.
- A finding needs code evidence. "This could break" is not enough. Read the
  rules in `### Finding discipline`
  of `references/report-format.md`.
- Apply every active category relevant to each changed section. Record skipped
  categories with a short reason.
- Append each finding immediately to its category file as it's found, not
  batched at the end.
- Use repository-relative paths in every finding location.
- Keep one file per category. It makes follow-up clear.
- A standalone `varde-review fix` run only processes findings labelled
  `Label: auto-fix` — mislabeled findings are silently skipped, so set the label
  carefully at review time.
- `varde-review fix` reads this skill's category files for automated fixes and
  triage.

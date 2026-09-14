---
name: varde-review
description: >
  TRIGGER: Review a target — code changes or a requested area — with a
  structured, multi-category pass that writes report-only, persisted findings.
  SKIP: Skip when the user asks to apply fixes (use /varde-review-fix), implement
  a change, or plan work; also skip a lightweight inline tidy of just-changed
  lines with no persisted findings (use /varde-simplify).
  Example phrases: "review this diff" or "find bugs in these changes".
---

## Entry point dispatch

| Invocation | Action |
|---|---|
| *(none)* | Run `default` mode: `CORRECTNESS`, `CODE`, `ARCHITECTURE`. |
| `--mode full` | Run all 10 categories, filtered by relevance. |
| `--mode <category>` | Run that single category only. |
| `--scope <text>` | Filter detected sections by keyword or substring. |

## Workflow

1. **Load the recipes.** Load `references/RECIPES.md` for the curated
   procedures behind this skill's operations. Check once per session
   whether the `varde-code` CLI (an optional tool, installed on PATH) is available: run `command -v varde-code >/dev/null 2>&1`.
   If present, load `references/VARDE-CODE-CLI.md` for optional
   operations that add structural/graph signal to step 4's code analysis.
   If it isn't, ignore that file and use the plain grep/read workflow
   as-is.
2. **Resolve mode and spec source.** Parse `--mode`, validate it, and state
   the resolved mode and active categories before proceeding; when
   `CORRECTNESS` is active, resolve the correctness spec source. Full
   procedure: the `## Resolve mode and spec source` section of
   `references/WORKFLOW.md`.
3. **Create the review folder.** Create it before any category work starts,
   so every subsequent step has a fixed `reviewDir` to write into. Full
   procedure: the `## Create the review folder` section of
   `references/WORKFLOW.md`.
4. **Analyze the changed code.** Read the diff and changed files directly,
   run the project's own lint/test/typecheck commands if any exist, and grep
   for known anti-patterns. Write findings straight into the review folder.
   Full procedure: the `## Analyze the changed code` section of
   `references/WORKFLOW.md`.
5. **Detect sections.** Load the configured sections or auto-detect them,
   then apply `--scope` filtering. Full procedure: the `## Detect sections`
   section of `references/WORKFLOW.md`.
6. **Review each changed section.** Apply active categories together while
   reading each section. Full procedure: the `## Review each changed section`
   section of `references/WORKFLOW.md`.
7. **Roll up and report.** Build the in-memory rollup, confirm the review
   folder is complete, and report results to the user. Full procedure: the
   `## Roll up and report` section of `references/WORKFLOW.md`.
8. **Reflect and consolidate.** Invoke `varde-reflect source=varde-review` — it
   captures friction scoped to this skill's own execution and harvests any durable
   knowledge the work produced (no handoff mid-session). If `varde-reflect` isn't
   installed, fall back to `varde-friction` with the same scope.

Report only — do not modify source files. If a step fails outright, report a
hard error and stop.

## Gotchas

- Use a subagent only for a section exceeding available context. Give it a
  refute mandate and verify its `high`/`critical` candidates before persisting.
  Full wording: `## Review each changed section` in `references/WORKFLOW.md`.
- A finding is a code-confirmed defect with evidence, not a "this could break"
  — the bar and calibration rules live in the `### Finding discipline` section
  of `references/FORMAT.md`.
- Apply every active category relevant to each changed section. Record skipped
  categories with a short reason.
- Append each finding immediately to its category file as it's found, not
  batched at the end.
- Use repository-relative paths in every finding location.
- Keep one file per category. It preserves attribution and targeted follow-up.
- Only findings with `Label: auto-fix` are processed by `/varde-review-fix` in
  default mode — mislabeled findings are silently skipped, so set the label
  carefully at review time.
- `/varde-review-fix` reads this skill's category files for automated fixes and
  triage.

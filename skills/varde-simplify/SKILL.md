---
name: varde-simplify
description: >
  TRIGGER: Apply a lightweight clarity pass scoped to recently changed code
  only — tighten naming, remove redundancy, and fix inconsistencies within the
  changed lines, then verify with tests. Edits inline, no findings store.
  SKIP: This is scoped to the diff, not a scaled-down review. Skip when the user
  wants to audit unchanged code or wants a structured multi-category pass with
  persisted findings (use /varde-review), or wants to apply an existing review's
  findings (use /varde-review-fix).
  Example phrases: "simplify what I just changed" or "clean up this diff".
---

## Entry point dispatch

| Invocation | Action |
|---|---|
| *(none)* | Diff scope = uncommitted changes (working tree + staged) against `HEAD`. |
| `--staged` | Diff scope = staged changes only. |
| `--ref=<ref>` | Diff scope = changes against `<ref>` instead of `HEAD`. |
| `<path> [<path> ...]` | Diff scope = the named files, still line-ranged against `HEAD` (or `--ref`). |

## Workflow

1. **Load the references.** Load `references/SCOPE.md` for how changed-line
   ranges are computed and merged from `git diff`. Load
   `references/PRINCIPLES.md` for the simplification principles that govern
   every edit this skill makes. Check once per session whether the
   `varde-code` CLI (an optional tool, installed on PATH) is available: run `command -v varde-code >/dev/null 2>&1`.
   If present, load `references/VARDE-CODE-CLI.md` for optional
   diff-scoped symbol lookups that can replace some of step 5's context
   reads. If it isn't, ignore that file and use the plain Read workflow
   as-is.
2. **Keep the source location.** Run in the checkout that owns the selected
   diff. A new worktree starts clean and cannot simplify the invocation's
   uncommitted changes. If concurrent editing makes that checkout unsafe, stop
   and ask the user to pause the competing work or invoke this pass against a
   committed `--ref` range instead.
3. **Compute scope.** Derive the changed-file list and line ranges (or
   whole-file for newly added files) per `references/SCOPE.md`. If no
   changes are found, report that and stop — never invent scope.
4. **State the plan.** Report the resolved diff source (working tree /
   staged / `--ref`) and the file list with their line ranges before editing
   anything.
5. **Apply edits.** One file at a time, per `references/PRINCIPLES.md`. Read
   surrounding code for context only — never edit outside a file's listed
   ranges. Newly added files may be edited in full.
6. **Verify.** Run the project's existing test command after each file's
   edits — when `varde-code` is available, use `tests_for_file` to scope this
   to the tests actually covering the edited file instead of the whole
   suite where the project's test runner supports targeting individual
   files; fall back to the full command otherwise. A failing run reverts
   that file's edits (`git checkout -- <path>` for a tracked file, or
   discard the edit for a new file) before moving to the next file — never
   leave the tree worse than before the pass started. A green run only proves
   behavior-preservation if the tests actually exercise the edited lines — if
   the edited lines have no covering test, say so in the report rather than
   treating the green run as proof.
7. **Report.** A short summary: files touched, what changed and why, and any
   worthwhile improvement that fell outside scope (name it, don't apply it).
8. **Reflect and consolidate.** Invoke `varde-reflect source=varde-simplify` — it
   captures friction scoped to this skill's own execution and harvests any durable
   knowledge the work produced (no handoff mid-session). If `varde-reflect` isn't
   installed, fall back to `varde-friction` with the same scope.

## Gotchas

- Never change behavior — this is a clarity/consistency pass only, not a
  feature or logic change. All existing tests must continue to pass.
- Never expand scope to unchanged lines, even when a fix would clearly be
  better there — name it in the summary instead of applying it. Auditing
  unchanged code is where false findings breed; the diff scope is the
  discipline that keeps this pass cheap and trustworthy.
- Newly added files are in scope in full; files with deletions-only hunks
  have nothing to simplify — skip them.
- This skill has no findings store and no review folder — it edits inline
  and reports a summary directly to its caller. Use `/varde-review` when
  persisted, triaged findings are needed instead; use `/varde-review-fix` to apply
  an existing review's findings.
- This pass edits the checkout containing its input diff. A caller's worktree
  remains valid because it contains that diff; this skill creates no worktree
  and never merges or cleans one up.

# Fix mode

The parent owns review orchestration and user triage. An Executor applies
findings only: it never prompts the user, decides a blank disposition, or
creates a companion plan. Read and edit the review Markdown directly (format:
`references/report-format.md`).

## Review-folder routes

Choose one route and pass the review folder explicitly:

| Route | Required context |
|---|---|
| Plan-owned review | `mode=build`, `plan_context`, `review_dir`, `repoRoot` |
| Standalone review folder | `mode=standalone`, `review_dir`, `repoRoot`; no `plan_context` |

Use `references/fix-pass.md` for eligibility and ID selection before loading a
complete finding. Return each non-applied finding that needs a decision to the
parent with its identifier, reason, and any `Escalated:` note: unverified,
rejected, unapplied, blank in a build, or non-eligible in a standalone run.

The parent supplies `review_dir`. For a PR number or URL, it first builds the
review folder with `references/fix-pr.md`.

## Parent workflow

1. **Check the tree.** Run `git status --porcelain` in `repoRoot`. A dirty
   tree stops build mode; in standalone mode, proceed in place only with the
   user's authorization.
2. **Select the review.** Confirm `review_dir/review.md` exists; take category
   order from its `## Categories` table and confirm each active category
   completed or was intentionally skipped. On a finding missing required
   fields, report its category and identifier and stop until a human repairs it.
3. **Plan-owned automated pass,** only when at least one finding is eligible:
   dispatch one Executor for `references/fix-pass.md` over the folder. With
   none eligible, go straight to triage. Standalone folders, including PR
   sources, skip this pass.
4. **Triage first** (`## Parent triage`). In a standalone folder, the fix
   request itself approves each eligible `auto-fix` finding with one reliable
   solution; record `Disposition: fix`, its solution, and the request as
   decision evidence (same as the `fix` row below). Wait only when other rows
   need a decision.
5. **One bounded build.** The parent dispatches one `varde-change`
   bounded build task (one subject, one Executor) covering every approved fix, with
   the selected `finding_ids`, each ID's concrete approved solution, and
   traceable user decision evidence. The Executor runs `fix-pass.md` over only
   those IDs. Never rerun review-fix over the whole folder for a user-selected
   finding.
6. **Close** (`## Closing`) and route obstacle evidence and reusable decisions
   to `varde-learn` or `varde-knowledge`.

## Executor

- In build mode with plan storage tracked, commit the round's code edits once
  at round end.
- For a PR source, commit verified fixes on the local PR branch; the Executor
  never pushes, posts comments, or resolves threads.

## Parent triage

Before any standalone build, the parent shows every unresolved blank finding in one inline table, then waits for the user's decision:

```
| # | Severity | Location | Summary | Escalated | Recommended |
|---|---|---|---|---|---|
| 1 | high | src/auth/token.ts:42 | accepts expired tokens | — | fix: reject expired tokens |
```

- Recommend `fix` for high severity or a contained, high-confidence change at
  one call site.
- Recommend `action-item` for a large, cross-package, or hot-path fix.
- Size wins: a large high-severity fix is an `action-item`.
- Discuss a build-blocking finding before dismissing it.

| User choice | Parent records |
|---|---|
| `fix` | `Disposition: fix`, the chosen concrete solution, and decision evidence; then dispatch as above |
| `dismiss` | The dismissal and its reason |
| `action-item` | A companion-plan task |
| `discuss` | Nothing; `Disposition` stays blank |

A disposition alone does not approve a particular solution; keep the decision
history when a later blocker prevents application.

### Companion plan

Create one per review at its first action item; add later action items as
tasks. Pre-fill each task's `#### Verification` from the finding title,
location, summary, and chosen solution, and link the task from the finding.

- Standalone review: `<working>/plans/<YYYY-MM-DD>-review-fixes-<target>/plan.md`.
- Review nested in a plan bundle: `<working>/plans/<plan-id>/<fix-id>/plan.md`,
  with `type: plan` and `source_review: <plan-id>/<review-id>` in frontmatter;
  keep its tasks and child concepts inside the parent bundle, and complete it
  before the parent plan.

## Closing

1. Report `automated: fixed/skipped/reverted` and
   `triage: fix/dismiss/action-item/deferred` counts, one line each, counting
   only decisions already recorded; leave parent-owned choices blank.
2. Set `triage_status`: `complete`, or `partial` when unresolved findings
   remain.

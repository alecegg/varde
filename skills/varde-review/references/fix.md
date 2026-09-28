# Fix mode

## One selected standalone finding

For an explicit request to fix one already recorded standalone finding, read
its category file and confirm the ID, current location, and one concrete
solution. Route a settled fix to bounded `varde-change` in the same turn; do
not create another report, run the automated pass below, or create a task or
companion plan. If the solution is ambiguous or required human-only approval
is missing, use Parent triage below. Plan-owned findings keep their existing
task flow.
For an `auto-fix` finding with one reliable solution, the user's named fix
request supplies decision evidence; a `triage` finding needs approval of its
specific solution.

Pass the review folder, finding ID, selected solution, and decision evidence
to the bounded contract. Scope both the category file and `review.md` (use
`--artifact` for each file outside the repository). Apply the normal pre-edit
gate. After source verification, change only that finding's `Disposition` to
`fix`, append a decision note linking the bounded subject and fix evidence,
and recompute `review.md`'s `triage_status` (`complete` if no unresolved
findings remain, otherwise `partial`). Then obtain final review and run the
complete checkpoint over source and review edits. Leave other findings
untouched.

The parent owns review orchestration and user triage. An Executor applies
findings only; it never prompts the user, changes a blank disposition based on
its own judgment, or creates a companion plan. Read and edit the review's
Markdown directly (format: `report-format.md`).

Choose one route and pass the review folder explicitly:

| Route | Required context | Findings processed |
|---|---|---|
| Plan-owned review | `mode=build`, `plan_context`, `review_dir`, `repoRoot` | `Disposition: fix` findings regardless of label. Blank findings go to parent triage; skip `dismiss`, `action-item`, and `escalated`. Apply the plan gate and task assertions below. |
| Standalone review folder | `mode=standalone`, `review_dir`, `repoRoot`; no `plan_context` | `Label: auto-fix` findings whose disposition is blank or `fix`. Skip `dismiss`, `action-item`, and `escalated`. |

Check eligibility before loading a complete finding, checking its location,
running the plan gate, backing up files, or making an edit. In a standalone
run, return non-eligible findings that still need a decision (including blank
`Label: triage`) to the parent. In a plan-owned build, return blank findings
to the parent for triage without applying them. In either route, return every
unverified, rejected, unapplied, or otherwise unresolved finding to the parent
with its identifier, reason, and any `Escalated:` note. The parent presents
the triage table and records the user's decision.

For a follow-up fix after triage, a single standalone finding uses the route
above. For plan-owned or multiple selected findings, the parent creates a
bounded build task with the selected `finding_ids`, the concrete approved
solution for each ID, and traceable user decision evidence, then dispatches it
through `varde-change build`. The Executor applies only those IDs and solutions;
missing or mismatched approval returns to the parent.
Do not rerun review-fix over the whole folder for a user-selected finding.

## Source routing

The parent resolves the review ID and supplies its `review_dir`. For a PR
number or URL, the parent follows `references/fix-pr.md` to turn unresolved
review threads and failing `gh pr` checks into a review folder before
dispatching the Executor. PR conversation comments supply context but do not
become thread findings. Missing `gh` or authentication stops before creating
a partial review.

Apply `references/review-gates.md` before edits and at completion; a
caller-approved plan can cover this pass when its scope and assumptions hold.

## Workflow

1. **Check the tree.** Run `git status --porcelain` in `repoRoot`. In build
   mode a dirty tree is an error; stop. In standalone mode, proceed in place
   only when the parent authorized it; otherwise return the dirty-tree result
   to the parent before editing. Per-finding isolation restores only the files
   a failed fix touched.
2. **Select the review.** Use the supplied `review_dir` and confirm
   `review.md` exists. Load category order from its
   `## Categories` table, confirm each active category completed or was
   intentionally skipped, and validate every finding's required fields; on a
   malformed finding, report its category and identifier and stop until a
   human repairs it.
3. **Automated pass.** Follow `references/fix-pass.md`.
4. **Return unresolved findings.** Do not perform human triage or create a
   companion plan in an Executor run. Return unresolved findings to the parent
   as deferred, preserving their `Escalated:` notes.
5. **Close.** See `## Closing`, below.
   For a PR source, commit verified fixes on the local PR branch and return the
   result to the parent. The parent handles any push choice; the Executor does
   not push, post comments, or resolve threads on GitHub.
6. Return obstacle evidence and reusable decisions to the parent for recording
   through `varde-learn` or `varde-knowledge`.

## Parent triage

After the Executor returns, the parent shows every unresolved blank finding in
one inline table, then waits for the user's decision:

```
| # | Severity | Location | Summary | Escalated | Recommended |
|---|---|---|---|---|---|
| 1 | high | src/auth/token.ts:42 | accepts expired tokens | — | fix: reject expired tokens |
```

The user may choose `fix`, `dismiss` with a reason, `action-item`, or `discuss`
(leave `Disposition: blank`). The parent records dismissals and reasons or
creates companion-plan tasks for action-items. For a chosen fix, the parent
records `Disposition: fix` and the chosen concrete solution with user decision
evidence, then uses the single-finding route above or creates a bounded
`varde-change build` task carrying those approvals and selected `finding_ids`
for plan-owned or multiple findings. Keep that decision history when a later
scope/spec/verification blocker prevents application; a disposition alone is
not approval of a particular solution.
Recommend `fix` for high severity or a contained, high-confidence change at
one call site; recommend `action-item` when the fix is large, crosses packages,
or touches a hot path. Discuss a build-blocking finding before dismissing it.

Create one companion plan per review at its first action item, and add each
later action-item as another task. Standalone review:
`<working>/plans/<YYYY-MM-DD>-review-fixes-<target>/plan.md`. Review nested in a
plan bundle: `<working>/plans/<plan-id>/<fix-id>/plan.md`, with `type: plan`
and `source_review: <plan-id>/<review-id>` as an extra traceability field in
frontmatter; keep its tasks and child concepts inside the parent bundle, and
complete it before the parent plan. Pre-fill each task's `#### Verification`
from the finding title, location, summary, and chosen solution, and link the
task from the finding block.

## Closing

Report `automated: fixed/skipped/reverted` and
`triage: fix/dismiss/action-item/deferred` counts on one line each, counting
only decisions already recorded in the review. Leave parent-owned choices
blank. Set `triage_status` (`complete`, or `partial` when unresolved findings
remain). In build mode, with plan storage tracked, commit the round's code
edits once at round end. Return the review folder and deferred findings to the
parent for triage and the next dispatch.

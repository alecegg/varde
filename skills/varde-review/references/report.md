# Report mode

## Choose the breadth

| The request is | Categories |
|---|---|
| A plain review, with no stated breadth | The default three: `CORRECTNESS`, `CODE`, `ARCHITECTURE` |
| A thorough or full review | All 10 categories in `references/report-categories.md`, filtered by relevance |
| A named concern — security, performance, and so on (tests → `CORRECTNESS`) | That single category |

If no category matches the named concern, list the ten categories and ask.
Do not guess.

## Workflow

1. **Resolve scope and target.** For an explicit code area without a diff/ref
   request, list tracked files with `git ls-files -- <area>` and untracked,
   nonignored files with `git ls-files --others --exclude-standard -- <area>`;
   inspect relevant consumers, even in a clean tree. For a diff/ref request, preserve
   changed-file scope and narrow it to any named area and its consumption path.
   Default diff target: working-tree changes vs `HEAD`, or the named ref;
   clean tree → changes since the nearest release tag
   (`git describe --tags --match 'v*' --abbrev=0 2>/dev/null`) or, if none,
   the merge base with `origin/HEAD` (`git merge-base HEAD origin/HEAD`).
   List changed files with `git diff --name-only <base>...HEAD` for a ref
   target; for uncommitted changes, use `git diff --name-only HEAD` plus
   `git ls-files --others --exclude-standard`. Exclude generated files,
   lockfiles, and vendored code only when they cannot affect the stated concern;
   name any exclusions. A requested whole-codebase pass lists tracked and
   untracked, nonignored files with the same commands without `<area>`, then
   uses successive batches per `## Split a large review`. Stop and
   say so when the resolved file list is empty. State area or diff scope, the
   resolved target, and active categories before reading code.
2. **Measure the read.** Before reading, total the bytes of the listed files
   and, for diff scope, the diff (`wc -c`); divide by 4 for approximate tokens. The reading
   budget is **60k tokens** (about 240 KB). Under it, review inline. Over it,
   follow `## Split a large review`.
3. **Resolve the spec source** when `CORRECTNESS` is active; the first found
   wins: acceptance criteria passed in (from `varde-change build`, the plan
   goal and plan-level criteria — verify every criterion), the active plan or
   task on disk, a spec under `<knowledge>/specs/` for the area, issue bodies
   that commits reference. With none, check internal consistency only. Pass the source to every delegated review.
4. **Create the review folder** before category work, per
   `references/report-format.md`, and pass the plan id to every delegate.
5. **Gather signals.** Run the project's lint/test/typecheck commands if any
   exist; file failures under matching categories. With `varde-code`, follow
   `references/varde-code.md` (review scoping). Grep for anti-patterns
   relevant to the active categories.
6. **Review.** Read every scoped file in full; for diff scope, also read the
   diff. For a deleted
   path, read its pre-deletion contents with
   `git show "$(git merge-base <base> HEAD):<path>"` for ref targets, using
   the merge base from the step 1 comparison. For working-tree deletions, use
   `git show HEAD:<path>`. Then inspect affected callers. In full mode, keep
   only categories whose `When` conditions apply, and state each skipped one
   once with its reason.
   Read each active category's guidance in
   `references/report-categories.md`, then apply all of them in one pass.
   Verify every `high` or `critical` finding yourself, per
   `### Finding discipline` in `references/report-format.md`.
7. Once per review, search `<knowledge>/` for specs, decisions, and patterns
   covering the reviewed area; when a finding breaks one, add its `Violates`
   link. Append each finding to its category file (`references/report-format.md`)
   as you find it.
8. **Roll up and report.** Read each category file, confirm one exists for
   every active category that ran, and update `review.md`. Tell the user:
   "Review complete. <N> findings across <C> categories. Review folder:
   `<path>`." Name skipped categories with their reasons. If complexity or
   readability findings exist, suggest `varde-change build` with the refactor
   posture.
9. Record real obstacles through `varde-learn`; record reusable decisions
   through `varde-knowledge`.

## Review-gate evidence

When the caller supplies a `varde-workflow` subject id for pre-edit or final
implementation review, inspect that phase and base the verdict on the current
contract, baseline, change fingerprint, and verification evidence. Write the
reviewer's JSON evidence record and submit it directly with
`varde-workflow review record`, using the exact `data.version` from inspect.
The CLI stores the record in the subject's configured working store; this is
the reviewer's only required write outside the active review folder. A report
file or coordinator-entered verdict does not satisfy the gate. If the review
CLI is unavailable, stop the gate review and report why.

## Split a large review

Split the listed files into chunks that each fit the budget; split an oversized
file into line ranges so its full contents are covered. Review up to three
chunks per batch, then continue until every scoped file is covered. Keep
completed findings in the review folder between batches and report any files
that could not be read.

Give each chunk to one report-only `review` subagent with the active
categories, the spec source, the chunk's files or line ranges, and resolved absolute
`<working>`/`<knowledge>` paths. Each uses those paths without re-resolving and
returns findings in the finding format after trying to disprove its own candidates, and writes
nothing. You write every category file, verify each returned `high` or
`critical` finding in the code, then run one cross-chunk pass after the final
batch for
`ARCHITECTURE` and `API-DESIGN` using dependents and the returned findings.

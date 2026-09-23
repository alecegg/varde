# Report mode

## Choose the breadth

The ten category names are `code`, `architecture`, `security`, `readability`,
`correctness`, `resilience`, `observability`, `performance`, `api-design`, and
`data-integrity`.

| The request is | Categories |
|---|---|
| A plain review, with no stated breadth | The default three: `CORRECTNESS`, `CODE`, `ARCHITECTURE` |
| A thorough or full review | All 10, filtered by relevance |
| A named concern — security, performance, tests, and so on | That single category |

If no category matches the named concern, list the ten categories and ask.
Do not guess. If the user names a keyword, path, or area, filter the detected
sections to it. State the resolved breadth and active category list first.

## Choose the target

| Working tree state | Review |
|---|---|
| Working tree has uncommitted or staged changes | Review those changes against `HEAD` |
| User names a branch, range, or PR | Review exactly that target |
| Repository is clean and no base is named | Review commits since the nearest merge or tag. Use `git describe --tags --abbrev=0` or `git log --merges -n1 --format=%H`, whichever is nearer `HEAD` |

Tell the user which target you resolved and how before reading code. For the
third row, also offer a whole-codebase pass in the same message. For "review
this repo", send recent commits to one reader and every file to another. Do
not guess silently. Repeated requests could review different code.

## Workflow

1. **Load the instructions.** Read `references/report-recipes.md` for common
   commands, `references/report-routing.md` for specialist routing, and
   `references/report-candidates.md` for the coordinator candidate contract.
   Read `references/varde-code.md` when that CLI is on PATH. It adds commands
   with call-graph and structure details for step 4. If you have not read the
   changed area this session, run its `nav_map` command before step 4. Section
   detection uses directory heuristics. `nav_map` shows the subsystem layout.
2. **Resolve the spec source.** When `CORRECTNESS` is active, resolve the
   correctness spec source. Full procedure: `## Spec source` below.
3. **Create the review folder.** Create it before reviewing categories.
   Use its `reviewDir` for all later files. Full
   procedure: `## Create the review folder` below.
4. **Analyze the changed code.** Read the diff and changed files directly,
   run the project's own lint/test/typecheck commands if any exist, and grep
   for known anti-patterns. Write findings straight into the review folder.
   Full procedure: `## Analyze the changed code` below.
5. **Detect sections.** Load the configured sections or auto-detect them,
   then narrow to the area the user named, if any. Full procedure:
   `## Detect sections` below.
6. **Review each changed section.** Check all active categories while
   reading each section. Full procedure: `## Review each changed section`
   below.
7. **Count and report.** Count the findings, confirm the review
   folder is complete, and report results to the user. Full procedure:
   `## Roll up and report` below.
8. **Record lessons.** Invoke `varde-knowledge reflect`, scoped to this run. It
   records friction and durable lessons only — a handoff belongs at a
   session boundary, which this is not.

Report only. Do not modify source files. If any step fails outright, report a
hard error and stop.

## Spec source

When `CORRECTNESS` is active, use these spec sources in order:

- Acceptance criteria passed in the invocation prompt.
- The active task or plan document, if one exists on disk.
- Commit issue references and their issue bodies.
- A matching specification document.
- The user, if no source is available.

If no source is found, check internal consistency only. Pass the resolved
source as `{{spec_source}}` to any delegated correctness review.

When spawned by `varde-change build`, treat the passed plan goal, plan-level
acceptance criteria, Feature Impact, and verification evidence as the primary
review specification. Verify every plan-level acceptance criterion.

## Create the review folder

Create the review folder before category work. Save its path as `reviewDir`.
Use it for every later file. When `originating_plan_id` is present, create the
folder under
`<working>/plans/<originating_plan_id>/<review-id>/`. Use
`<originating_plan_id>/<review-id>` as the compound id. Keep category files
beside `review.md`. Without a plan id, use
`<working>/reviews/<review-id>/`. Create the folder with `mkdir -p`.
Write `review.md` and `index.md` directly. Generate sibling `index.md` as
nav-only metadata.

Pass `originating_plan_id` through every delegated review prompt. Treat a
nested review as complete when its `triage_status` is `complete`. Keep its
action-item plans as separate nested children of the same plan bundle.

## Analyze the changed code

After creating the review folder, read the changed code yourself. This manual
review requires every finding to come from code you read:

1. For the target resolved in `## Choose the target`, collect the diff with
   `git diff <base>...HEAD`, or `git diff HEAD` for uncommitted changes. Read
   every changed file in full, not just the hunk. For an approved whole-codebase
   pass, no diff exists. Use the detected sections as the read list.
2. If the project has lint, test, or typecheck commands, check `package.json`,
   a `Makefile`, or similar. Run those commands and report failures as findings.
3. If `varde-code` is available, read `references/varde-code.md`. Run its
   scoping pass over changed files before the grep step. Include hotspots,
   blast radius, dependents, `tests_for_file`, and a `scan` rule-pack pass.
   Treat its output as another candidate list, not a review limit. A changed
   file with no covering tests (`tests_for_file` returns empty) raises the
   CORRECTNESS severity. See `references/report-categories.md`.
4. Grep for anti-patterns relevant to the active categories. Examples include
   empty catch blocks, string-concatenated queries, `TODO`/`FIXME` markers, and
   duplicated blocks. Read shortlisted locations more closely.
5. Use one subagent only when a section exceeds available context. Give it a
   bounded file slice. Tell it to try to disprove candidates and verify its
   own candidates, as required by `## Review each changed section`.

Write findings straight into the review folder's category files as you find
them (see `## Review each changed section` below), then move to the next
section. Each section is analyzed once.

## Detect sections

First check for a project config declaring review sections, such as a
`review.sections` array in repo settings. If none exists, auto-detect
top-level directories. If the repository only has `src/`, group by
subdirectory. If the structure is ambiguous, use `src` and `non-src`, and warn.

If the request names an area, keyword, or path, filter sections to it. Warn and
stop when filtering produces no sections.

## Review each changed section

For each changed section, review all relevant active categories together:

1. Collect changed files with `git diff --name-only HEAD -- <section>`.
   Fall back to `main...HEAD` when needed. Skip sections with no files.
2. In full mode, keep only categories whose `## When relevant` conditions
   apply. State any skipped category and its reason once per section.
3. Read each remaining category's `## <NAME>` and `### How to check`
   guidance. Also read relevant knowledge patterns and specification inputs.
4. Read each changed file in full with its diff. Apply every remaining
   category checklist in one pass. Confirm candidates in the actual code. Run
   relevant project checks once, then assign failures to matching categories.
5. Use a subagent only when the section exceeds available context. Tell it to
   try to disprove candidates. Verify every `high` or `critical` candidate
   yourself.
6. Before each write, grep or glob project docs for the affected feature.
   Link any matching concept.
7. Append each finding to its category file by applying a targeted edit, or
   by creating the file if it does not yet exist. Load the existing file
   first to preserve prior findings. The file must have valid frontmatter
   (`review-category` metadata, see the `## Category file format` section of
   `references/report-format.md`) and the full updated body (required fields per the
   `## Finding format` section of `references/report-format.md`).

Use `auto-fix` only when the fix is precisely describable and follows an
established project pattern. Otherwise use `triage`. Keep `disposition` blank
until the follow-up pass.

### Finding format

Read the `## Finding format` section of `references/report-format.md` before
writing findings. Every category file uses its exact field markers.

Every finding summary must explain the issue, impact, and evidence. Link the
review folder and relevant project docs when useful.

## Roll up and report

Read each category file and build the rollup. Confirm the review folder
contains `review.md`, generated nav-only `index.md`, and one file for every
active category that ran.
Report skipped category-section pairs and their reasons.

Tell the user: "Review complete. <N> findings (<A> scan advisories) across
<S> sections and <C> categories. Review folder written to `<path>`."

If complexity or readability findings exist, offer a refactor pass that
preserves behavior. Wait for the user to accept it.

## Gotchas

- Use a subagent only for a section exceeding available context. Tell it to
  try to disprove candidates. Verify its `high`/`critical` candidates before
  persisting them. See `## Review each changed section` above.
- Every finding needs code evidence. "This could break" is not enough. Read
  `### Finding discipline` in `references/report-format.md`.
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

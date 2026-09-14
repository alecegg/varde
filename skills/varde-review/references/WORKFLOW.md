# Review workflow

Workflow steps 2-7 for varde-review, in order.

## Resolve mode and spec source

### Mode resolution

Parse the invocation for a `--mode` argument:

| Argument | Mode | Active categories |
|----------|------|-------------------|
| *(none)* | `default` | `CORRECTNESS`, `CODE`, `ARCHITECTURE` |
| `--mode full` | `full` | all 10, filtered by relevance |
| `--mode <category>` | `single` | that category only |

Valid single-category names: `code`, `architecture`, `security`, `readability`,
`correctness`, `resilience`, `observability`, `performance`, `api-design`,
`data-integrity`.

If the value is invalid, print the valid options and exit. State the resolved
mode and active categories before proceeding.

### Spec source

When `CORRECTNESS` is active, hunt for the spec source in this order:

- Acceptance criteria passed in the invocation prompt.
- The active task or plan document, if one exists on disk.
- Commit issue references and their issue bodies.
- A matching specification document.
- The user, if no source is available.

If no source is found, check internal consistency only. Pass the resolved
source as `{{spec_source}}` into any delegated correctness review.

When spawned by `/varde-build`, treat the passed plan goal, plan-level
acceptance criteria, Feature Impact, and verification evidence as the primary
review specification. Verify every plan-level acceptance criterion.

## Create the review folder

### Setup

Create the review folder before category work. When `originating_plan_id` is
present, create it under
`memory-bank/working/plans/<originating_plan_id>/<review-id>/review.md` and
use the compound id `<originating_plan_id>/<review-id>`; keep category files
beside `review.md`. When no plan id is present, preserve the standalone path
under `memory-bank/working/reviews/<review-id>/`. Create the folder with
`mkdir -p` and write `review.md` and `index.md` directly. Generate sibling
`index.md` as nav-only metadata. The folder path fixes `reviewDir` for this
run.

Carry `originating_plan_id` through every delegated review prompt. A nested
review is terminal when its `triage_status` is `complete`; its action-item
plans remain separate nested children of the same plan bundle.

## Analyze the changed code

### Code analysis

After creating the review folder, analyze the changed code directly — there
is no scan pipeline to run. This is a manual/LLM-driven pass, not a
tool-driven static scan:

1. Collect the diff: `git diff <base>...HEAD` (or `HEAD` for uncommitted
   changes). Read every changed file in full, not just the hunk, so
   surrounding context is available.
2. If the project has its own lint, test, or typecheck commands (check
   `package.json` scripts, a `Makefile`, or similar), run them and note any
   failures — these are legitimate findings in their own right.
3. If the `varde-code` CLI is available (`references/VARDE-CODE-CLI.md`),
   run a scoping pass over the changed files — hotspots, blast radius,
   dependents, tests_for_file, and a `scan` rule-pack pass — before the
   grep step below. Treat its output as an additional candidate list
   alongside grep's, not a gate on what gets reviewed. A changed file with
   no covering tests (`tests_for_file` returns empty) is a severity signal
   for CORRECTNESS, not just a note — see the `## CORRECTNESS` section of
   `references/CATEGORIES.md`.
4. Grep for known anti-patterns relevant to the categories in scope (e.g.
   empty catch blocks, string-concatenated queries, `TODO`/`FIXME` markers,
   obviously duplicated blocks) to shortlist places worth a closer read.
5. Use one subagent only when a section exceeds available context. It reads a
   bounded file slice and reports candidates under the same refute mandate and
   self-verification as `## Review each changed section`.

Write findings directly into the review folder's category files as they're
found (see `## Review each changed section` below) — do not batch
them into a separate note first. Do not re-run this analysis once a section's
findings are recorded; move on to the next section.

## Detect sections

### Section detection

Look for a project config file declaring review sections (e.g. a
`review.sections` array in a repo-specific settings file), if the project
has one. Otherwise, auto-detect top-level directories. For a repository with
only `src/`, group by subdirectory instead. Fall back to `src` and `non-src`
when directory structure is ambiguous, warning rather than silently
proceeding.

If `--scope <text>` was provided, filter sections by keyword or substring.
Warn and exit if filtering produces no sections.

## Review each changed section

### Review execution

For each changed section, review relevant active categories together:

1. Collect changed files with `git diff --name-only HEAD -- <section>`.
   Fall back to `main...HEAD` when needed. Skip sections with no files.
2. In full mode, keep only categories whose `## When relevant` conditions
   apply. State any skipped category and its reason once per section.
3. Load each remaining category's `## <NAME>` and `### How to check` guidance,
   plus relevant knowledge patterns and specification inputs.
4. Read each changed file in full with its diff. Apply every remaining
   category's checklist in one pass. Confirm candidates in actual code. Run
   relevant project checks once, then assign failures to the matching category.
5. Use a subagent only when the section exceeds available context. Give it a
   refute mandate and verify every `high` or `critical` candidate yourself.
6. Before each write, grep/glob the relevant project docs for the affected
   feature and link any matching concept.
7. Append each finding to its category file by applying a targeted edit, or
   by creating the file if it does not yet exist. Load the existing file
   first to preserve prior findings. The file must have valid frontmatter
   (`review-category` metadata, see the `## Category file format` section of
   `references/FORMAT.md`) and the full updated body (required fields per the
   `## Finding format` section of `references/FORMAT.md`).

Use `auto-fix` only when the fix is precisely describable and follows an
established project pattern. Otherwise use `triage`. Keep `disposition`
blank until the follow-up pass.

### Finding format

Load the `## Finding format` section of `references/FORMAT.md` before writing
findings. Every category file uses the exact field markers defined there.

Every finding summary should explain the issue, impact, and evidence. Link the
review folder and relevant project docs in the finding body when useful.

## Roll up and report

### After review

Load each category file and build the in-memory rollup. Confirm the review
folder contains `review.md`, generated nav-only `index.md`, and one file for every active category that ran.
Report skipped pairs and their reasons.

Tell the user: "Review complete. <N> findings (<A> scan advisories) across
<S> sections and <C> categories. Review folder written to `<path>`."

If complexity or readability findings exist, offer a behavior-preserving
refactor pass. Do not invoke it automatically.

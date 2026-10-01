# Report mode

## Choose the breadth

| The request is | Categories |
|---|---|
| A plain review, with no stated breadth | The default three: `CORRECTNESS`, `CODE`, `ARCHITECTURE` |
| A thorough or full review | All 10 categories in `references/report-categories.md`, filtered by relevance |
| A named concern — security, performance, and so on (tests → `CORRECTNESS`) | That single category |

If no category matches the named concern, list the ten categories and ask.

## Workflow

1. **Resolve scope and target,** then state the scope, its `# target`, and the
   active categories before reading code, or stop if no files are listed:
   - Explicit code area: `scripts/review-scope.sh area [<area>]`.
   - Diff or ref: `scripts/review-scope.sh diff [--ref <ref>] [-- <area>]`.
   - Exclude generated files, lockfiles, and vendored code only when they
     cannot affect the stated concern, and name the exclusions.
2. **Measure the read:** compare the script's `# tokens` with the **60k-token**
   budget (about 240 KB); over it, follow `## Split a large review`.
3. **Resolve the spec source** when `CORRECTNESS` is active, using the first
   available in this order:
   1. Acceptance criteria passed in from `varde-change build` (the plan goal
      and plan-level criteria; verify every criterion).
   2. The active plan or task on disk.
   3. A spec under `<knowledge>/specs/` for the area.
   4. Issue bodies that commits reference.
   5. None: check internal consistency only.
4. **Create the review folder** before category work, per
   `references/report-format.md`.
5. **Gather signals:** file failures from the project's lint/test/typecheck
   commands under matching categories; with `varde-code`, follow
   `references/varde-code-cli.md`. For each changed file, query tests and
   dependents together:

   ```bash
   ROOT=$(git rev-parse --show-toplevel)
   varde-code batch --json '{"repoRoot":"'"$ROOT"'","calls":[
     {"mode":"tests_for_file","filePath":"src/foo.ts"},
     {"mode":"dependents","filePath":"src/foo.ts"}]}'
   ```

   Changed symbols used by dependents keep their signatures.

   Use `nav_map` for an unfamiliar area or multi-module diff. Reserve
   `hotspots` and `scan` for whole-repository review.
6. **Review** every scoped file in full, the diff for diff scope, and affected
   callers; for a deleted path (status `D`), read `git show <base>:<path>` with
   the script's `# base`. From `references/report-categories.md`, read only
   `## Rules for every category` and each active category's section; apply
   them in one pass (in full mode, only those whose `When` applies), and
   verify every `high` or `critical` finding yourself.
7. **Record** each finding in its category file as you find it. Add a
   `Violates` link when it breaks a spec, decision, or pattern found by one
   `<knowledge>/` search for the reviewed area.
8. **Roll up and report.** Confirm a category file exists for every active
   category that ran, update `review.md`, and tell the user the line below
   plus each skipped category with its reason:
   ```text
   Review complete. <N> findings across <C> categories. Review folder: `<path>`.
   ```

## Review-gate evidence

For a caller-assigned gate review, follow `references/review-gate-record.md`;
a report file does not satisfy the gate.

## Split a large review

1. Split the listed files into chunks that fit the budget, splitting an
   oversized file into line ranges so its full contents are covered.
2. For each batch of up to three chunks, give each chunk to one report-only
   `varde-reviewer` subagent with the active categories, spec source, the chunk's
   files or line ranges, and resolved absolute `<working>`/`<knowledge>`
   paths. Tell it to load only the rules and active sections of
   `references/report-categories.md` and `## Finding format` in
   `references/report-format.md`, not this file or `references/varde-code-cli.md`.
   It uses those paths without re-resolving, tries to disprove its own
   candidates, returns findings in the finding format, and writes nothing.
3. Write every category file yourself, verify each returned `high` or
   `critical` finding in the code, and keep completed findings in the review
   folder between batches.
4. Continue until every scoped file is covered, reporting files that could not
   be read. After the final batch, run one cross-chunk pass for
   `ARCHITECTURE` and `API-DESIGN` using dependents and the returned findings.

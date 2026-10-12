# Report mode

## Choose breadth

| Request | Categories |
|---|---|
| Plain review | `CORRECTNESS`, `CODE`, `ARCHITECTURE` |
| Thorough or full review | All relevant categories in `references/report-categories.md` |
| Named concern | That category; tests map to `CORRECTNESS` |

Every review also runs the Spec axis against the task, plan, or linked specs.
If no category matches a named concern, list the categories and ask.

## Report workflow

1. **Resolve scope and target,** then state the scope, its `# target`, and the
   active categories before reading code, or stop if no files are listed:
   - Explicit code area: `scripts/review-scope.sh area [<area>]`.
   - Diff or ref: `scripts/review-scope.sh diff [--ref <ref>] [-- <area>]`.
   - Exclude generated files, lockfiles, and vendored code only when they
     cannot affect the stated concern, and name the exclusions.
   Record target, scope, exclusions, and categories in one `review.md`; read
   `# base` for deleted-file context (step 4). Compare the helper's `# tokens`
   with the 60k-token budget; over it, follow `## Split a large review`.
2. For the Spec axis, use the first available spec: caller-supplied plan
   criteria (verify each); the active plan or task; `<knowledge>/specs/`;
   issues referenced by commits; otherwise check internal consistency only.
3. Create the review folder and `review.md` before reading code, following
   `references/report-format.md`. Run relevant lint, test, and typecheck
   commands; use `varde map batch` to query tests and dependents for changed
   files. For each changed file, use `calls`: `{"mode":"tests_for_file","filePath":"<f>"}` and `{"mode":"dependents","filePath":"<f>"}`.
   Flag stale dependent calls under active `API-DESIGN`, else `CORRECTNESS`.
   Use `nav_map` for unfamiliar or multi-module scopes; reserve `hotspots` and
   `scan` for whole-repository reviews.
4. Review the diff and necessary context; for area scopes, review listed files.
   Read broader files only when a changed contract or unresolved evidence
   requires it. For deleted paths, read `git show <base>:<path>` using `# base`.
   From `references/report-categories.md`, apply the Spec axis and the active
   Standards categories in one pass. Cover all changed lines with enough
   context and verify every high/critical candidate.
5. Record findings and evidence in `review.md`. Link `Violates` when a search
   finds a relevant spec, decision, or pattern the finding breaks.
6. Mark each active category `complete` or `skipped` with its finding count.
   Report the completion line and each skipped category with its reason:
   ```text
   Review complete. <N> findings across <C> categories. Review folder: `<path>`.
   ```

## Review report header

A caller-assigned review writes the same `review.md` header (`verdict`,
`reviewer`, `base`, `head`) in `references/report-format.md`; `varde plan
conclude` checks it.

## Split a large review

Over the 60k-token budget, divide the review into logical units (module, feature, commit series), each within budget, and give each to a report-only reviewer. Verify every high or critical finding yourself, then run one cross-unit pass for architecture and API design.

---
topic: varde-review/report-review
version: 1
summary: Prepare the report folder, read the diff, and record results
---

## Report review

### 2. Prepare the report

- Create the folder and `review.md` before reading code, using `references/report-format.md`.
- Query tests and dependents with `varde map batch` and `calls` for each changed file.
- Flag stale dependent calls under active `API-DESIGN`, else `CORRECTNESS`.
- Use `nav_map` for unfamiliar or multi-module scopes; reserve `hotspots` and `scan` for whole-repository reviews.

### 3. Review the diff

- Read the diff and necessary context, including listed files for area scopes.
- If changed or listed files include tests, read `references/test-quality.md`; it is a gate, not optional.
- Read broader files only when a contract or unresolved evidence requires it.
- For deleted paths, use `git show <base>:<path>` with the reported `# base`.
- For a plan architecture pass, apply the categories chosen in the breadth step.
- Verify every high-severity candidate.

### 4. Record results

- Record findings and evidence in `review.md`.
- Link `Violates` when a search finds a relevant spec, decision, or pattern.
- Mark each active category `complete` or `skipped` with its finding count; report skipped reasons.

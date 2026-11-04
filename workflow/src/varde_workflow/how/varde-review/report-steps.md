---
topic: varde-review/report-steps
version: 1
summary: Resolve review scope and budget, and split large reviews
---

## Report steps

Report mode: for a named concern with no matching category, list the categories and ask. For a plan review, read gate output first, then run the conformance route (`references/conform.md`) inside the same pass for Spec.

### 1. Resolve scope

- For an area, run `scripts/review-scope.sh area [<area>]`.
- For a diff or ref, run `scripts/review-scope.sh diff [--ref <ref>] [-- <area>]`.
- For a plan review, select the architecture and code categories the diff needs.
- State `# target`, scope, exclusions, and active categories before reading code.
- Stop if no files are listed.
- Exclude generated files, lockfiles, or vendored code only when they cannot affect the concern, and name those exclusions.
- Compare `# tokens` with the 60k budget; split larger reviews as below.

### Split a large review

Over the 60k-token budget, divide the review into logical units (module, feature, commit series), each within budget, and give each to a report-only reviewer. Verify every high-severity finding yourself, then run one cross-unit pass for architecture and API design.

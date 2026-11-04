# Report mode

## Choose breadth

| Request | Categories |
|---|---|
| Plain review | `CORRECTNESS`, `CODE`, `ARCHITECTURE` |
| Thorough or full review | All relevant categories in `references/report-categories.md` |
| Named concern | That category; tests map to `CORRECTNESS` |

Read `references/report-categories.md` for category definitions in every
review. A plan review also runs the conformance route
(`references/conform.md`) inside the same pass.

## Outcomes

- Standalone reviews check the available Spec (or internal consistency if none applies) and run relevant lint, tests, and typechecks. A plan review reads gate output first.
- A named concern with no matching category: list the categories and ask.
- `# target`, scope, exclusions, and active categories are stated before code is read; no listed files means stop.
- The review folder and `review.md` exist before code is read (`references/report-format.md`).
- Generated files, lockfiles, or vendored code are excluded only when they cannot affect the concern, and the exclusions are named.
- Reviews over the 60k-token budget are split into units, each reviewed report-only. Every high-severity finding is verified; one cross-unit pass covers architecture and API design.
- If changed or listed files include tests, `references/test-quality.md` is applied; it is a gate, not optional.
- Findings carry evidence in `review.md`; `Violates` links a relevant spec, decision, or pattern found by search; every high-severity candidate is verified against the code.
- Each active category is marked `complete` or `skipped` (with reason) and its finding count.

## Validation

Scope comes from `scripts/review-scope.sh` (`# target`, `# base`, `# tokens`). End with:

```text
Review complete. <N> findings across <C> categories. Review folder: `<path>`.
```

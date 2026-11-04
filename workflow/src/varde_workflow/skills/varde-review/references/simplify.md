# Simplify mode

## Principles

- Preserve behavior and rationale comments; favor readability over brevity;
  keep abstractions that earn their place; no nested ternaries.
- Keep security and safety code (auth, validation, data-loss guards,
  accessibility) even when it looks dead.
- Never weaken an assertion, loosen a type, or narrow validation to pass a
  test.

## Outcomes

- Only committed work is edited, inside the changed-line ranges; uncommitted changes in scope stop the work until the user commits or allows a WIP commit. Empty ranges: report that and stop.
- A changed symbol used outside scope keeps its name and signature; replacing new code with a call to an existing helper is in scope.
- The project's tests ran once after all edits (only `tests_for_file` when the runner can target files); say if they do not exercise the edited lines.
- Edit ranges come from `scripts/change-ranges.sh`.
- Simplify edits get the one independent review per change.
- The report lists files touched, what changed, why, and any obstacle, plus worthwhile out-of-scope improvements as unapplied recommendations.

# Refactor Posture

## Purpose

Behavior-preserving structural changes — restructuring or simplifying code without changing observable behavior. The full test suite (or, when scoped, the relevant subset) serves as the invariant guard.

## Bootstrap

1. If `memory-bank/knowledge/pattern/` exists, read it.
2. Determine the target in priority order:
   a. An explicit argument (file glob, directory, or free-text direction such as "simplify the auth module") — use it as-is.
   b. Otherwise, grep/glob the repo's findings directory (e.g. `memory-bank/knowledge/findings/`, if the repo has one) for the latest open review findings.
      - Findings found: read them and use as the target. Confirm the finding's `locations` still carries the complexity it claims — if the code-intelligence skill is available, use it to check complexity metrics for each location; otherwise read the file directly and judge complexity by eye. If a location doesn't show up, re-check the finding's `locations` field before proceeding — it may point somewhere more specific than assumed.
      - No findings found: ask the user for direction, or fall back to the structural goal stated by the task if one was given.
3. For each target file, find its exact covering tests — if the code-intelligence skill is available, use it to look up tests for the file; otherwise check for a sibling test by naming convention or grep for imports of the target file in test directories. If tests are found, read them in full before making any edits. If none are found, write a characterization test at the seam (see EXECUTION.md's seam definition) before making any structural edit, so behavior preservation still has a baseline to verify against. Only treat the target as blocked if it genuinely cannot be exercised at all (e.g. no reachable entry point).

## Cadence

1. Run the full test suite (or, when working against a scoped target, the relevant subset) to establish a baseline. Record any pre-existing failures.
2. For each structural change or complexity finding, one at a time:
   a. **Read** — re-use the test list from Bootstrap step 3; read the target code and those tests in full.
   b. **Plan** — state the change and confirm it preserves exact behavior. If it would alter a public API, output format, or any other observable behavior, reject the plan and find an alternative.
   c. **Edit** — apply the one change.
   d. **Verify** — run the full test suite (or relevant subset, build, typecheck, or lint — see priority order below). If anything regresses, revert immediately.
   e. **Commit** the change if verification passes.
3. Repeat until the structural goal is achieved or all findings/directions have been addressed.
4. Report a summary (see Summary format below).

## Verification command priority

1. `npm test -- <test-path>` — the relevant test file, when the target is scoped.
2. `npm test` — full suite.
3. `npx tsc --noEmit` — typecheck the affected package.
4. The project's configured static-analysis/lint/scan tooling (if any) — run it when source files changed outside `memory-bank/`. Advisory only — if it fails on a suspected false positive, record it in the plan and proceed.

If the project uses a different language or toolchain, run the equivalent verification for that toolchain.

## When to use

- When the task is explicitly a refactor or simplification.
- When `out_of_scope` explicitly prohibits behavior changes.
- When the task references unaddressed review findings (complexity, readability) from the `findings` bundle.
- When the user gives explicit direction to simplify, with no task required (`/varde-build posture=refactor [target=<target>]`).

## Reference

### What counts as a structural change / simplification

A behavior-preserving change that restructures or reduces code without altering observable output. Examples:
- Extracting a function, renaming, or moving a module.
- Inlining a function called from only one call site — confirm the call count before inlining, e.g. via the code-intelligence skill's caller lookup, or by grepping for the function name across the codebase; if it has more than one real caller (not just importing files), this is not a valid inline target.
- Replacing a switch statement with a lookup table.
- Removing dead code or unreachable branches.
- Consolidating duplicate logic into a shared helper.
- Flattening nested conditionals.

Do not:
- Rename variables or types as a side effect (that is cleanup, not a structural change).
- Extract shared logic to a new module unless the extraction reduces complexity.
- Change public APIs, error messages, log output, or wire formats.

### Behavior preservation

Exact behavior preservation means: for the same inputs, the code produces the same outputs (stdout, stderr, return code, side effects) and the same test results (same number of passing tests, no new failures). If a change alters any of these, it is not behavior-preserving — reject and revert.

### Summary format

```markdown
## Refactor summary

| File | Change | Verification |
|------|--------|---------------|
| src/foo.ts | Inlined helper | `npm test -- src/foo.test.ts` (passed) |
```

If no changes were made, state: "No behavior-preserving changes found."

### Input resolution examples

- No argument — looks for the latest open findings in the `findings` bundle, or the task's stated structural goal.
- `target=src/auth/` — operates on all files under `src/auth/`.
- `target=simplify the payment processing pipeline` — free-text direction.

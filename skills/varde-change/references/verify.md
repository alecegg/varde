# Standalone verification

Read-only: never fix, tick criteria, or change status.

## Resolve the target

| Request | Target |
|---|---|
| Plan identifier or slug | Matching `<working>/plans/<plan-id>/plan.md` |
| Feature or plan set | The plan, or every plan in its folder |
| No target | Most recent completed date-prefixed plan; none: report that and stop |

List ambiguous slug matches and ask once.
State the resolved identifier and current status.

## Verify

1. Read `## Acceptance criteria`. Stop if missing.
2. Ignore checkbox state; a check is a claim, not evidence, and an unchecked
   one is not an automatic failure.
3. Read each adjacent `tasks/*.md` status and Progress evidence.
4. Run every criterion's `assert:` command or structural check, exactly as
   written — never silently substitute a different assertion, and run broad
   project checks only when a criterion asks for one.
   Compare its exact expected result.
   Record exit codes or match counts.
5. For every `retrieve:` clause, read only named files.
   Compare the requested outcome and record its supporting line.
6. Classify every criterion:
   - `passed`: evidence matches expectations.
   - `failed`: evidence exists but contradicts expectations.
   - `unavailable`: evidence cannot be gathered — including a missing command
     or a moved file.
7. Report each criterion with its evidence.
   Finish with outcome counts and plan status.

A UI check needs a browser tool from your own tool list (harness tools do not
appear on `PATH`); without one it is
`unavailable`, never passed. Never infer rendering from source or HTTP. Use
only user-supplied credentials and submit no form that changes real data.

# Standalone verification

Read-only: never fix, tick criteria, or change status.

## Outcomes

- The target plan (`<working>/plans/<plan-id>/plan.md`) is resolved, and its identifier and current status are stated. With no named target the most recent completed plan is verified; a plan set verifies every plan in it. An ambiguous slug is listed and asked about once; with no plan to verify, report that and stop.
- Every criterion under `## Acceptance criteria` is `passed` (evidence matches), `failed` (evidence contradicts) or `unavailable`. Unavailable means evidence cannot be gathered, such as a missing command or moved file. Verification stops only when that section is missing.
- The report gives each criterion with its evidence, then outcome counts and plan status.

## Validation

- Checkboxes are claims; judge each criterion by evidence, and read each adjacent task's status and `Progress`.
- Every `assert:` command or structural check ran as written, with no substituted assertion. Broad checks ran only when a criterion asked. Exit codes or match counts are recorded.
- Each `retrieve:` read only its named files and records the supporting line.
- A UI check used a browser tool from your tool list; without one it is `unavailable`, never passed. Rendering is never inferred from source or HTTP. Only user-supplied credentials were used, and no form changing real data was submitted.

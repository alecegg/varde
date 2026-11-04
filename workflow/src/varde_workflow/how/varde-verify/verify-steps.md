---
topic: varde-verify/verify-steps
version: 1
summary: Resolve the target plan and the ordered steps for gathering evidence per criterion
---

## Resolve the target

| Request | Target |
|---|---|
| Plan identifier or slug | Matching `<working>/plans/<plan-id>/plan.md` |
| Feature or plan set | The plan, or every plan in its folder |
| No target | Most recent completed date-prefixed plan; none: report that and stop |

List ambiguous slug matches and ask once. State the resolved identifier and
current status.

## Verify

1. Read `## Acceptance criteria`; stop only if it is missing.
2. Ignore checkboxes; they are claims, and unchecked items do not fail
   automatically.
3. Read each adjacent `tasks/*.md` status and `Progress` evidence.
4. Run every `assert:` command or structural check as written; do not substitute
   another assertion. Run broad checks only when a criterion asks; record exit
   codes or match counts.
5. For each `retrieve:`, read only named files and record the supporting line.
6. Classify every criterion:
   - `passed`: evidence matches expectations.
   - `failed`: evidence exists but contradicts expectations.
   - `unavailable`: evidence cannot be gathered, including a missing command
     or a moved file.
7. Report each criterion with its evidence, then outcome counts and plan status.

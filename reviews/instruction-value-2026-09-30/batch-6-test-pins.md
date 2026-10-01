# Batch 6: loosen prose pins, then apply blocked rows

Approved by the user on 2026-09-30. Start after batches 3-5 are complete and committed.

## Tests

Change each pin so it asserts the contract (a command, flag, path, or rule keyword), not the exact prose.

1. `skills/tests/vendored-copies.sh`
   - Change the pinned memory paragraph so its git clause reads "Outside a repo, use `mv`, not `git mv`" (row 251).
   - Update all 7 SKILL.md copies together.
   - Keep the 7-copy identity check.
2. `skills/tests/session-diagnosis.sh`
   - Keep pins on CLI invocations, file routing, and safety contracts.
   - Drop pins on descriptive prose for rows 7, 84-90, 135, 156, 199.
3. `skills/tests/agent-review-correctness.sh` (lines 13 and 35)
   - Drop the pins on the legacy `git diff <head_sha>` text and on the "timestamps alone cannot" / "external target" text.
   - Keep the `unknown` label assertion and the behavioral fixture.

## Blocked rows to apply once the pins are loosened

- Row 251 (user D decision): the memory paragraph says "use `mv`, not `git mv`", in all 7 copies.
- Rows 78, 103, 106 (and 10): these cut the clause from individual copies. Superseded by 251: the shortened shared paragraph stays in every copy.
- Rows 7, 84-90, 135, 156, 199: varde-learn diagnose files, per batch-5.md.
- Row 219 (user D decision): cut the legacy handoff-link rule in `handoff-resume.md`.
- Row 252 (user D decision): shorten the "unknown" catch-all in `handoff-resume.md`, dropping the rationale.

Keep a pin wherever it guards behavior the audit scored 3 or higher.

## Follow-ups from the Opus re-review of 7855470 and f891c87

- M1: in build-micro-change.md:21, orchestrate.md:59, plan.md:190, and in shared review-gates.md:61 and review-gate-plan.md:7, run `python3 <skill-dir>/scripts/risk-tier.py <scope-path>...` from the repository root.
- L1: in varde-knowledge handoff-resume.md:28, use `python3 <skill-dir>/scripts/handoff-snapshot.py`.
- L2: in varde-manage scan-author.md, add an Optional bullet: "`name`, `description`, `remediation`: unvalidated but shown in scan output; set them like the built-ins."
- L3: in varde-prototype logic-track.md, restore a round line: "Each round, probe one missing action, scenario, or state field."
- N1 and N2: reflow handoff-write.md:23, visual-track.md:38-39, and varde-toz SKILL.md:8. In visual-track, add "otherwise ask per the round rules".
- recurrence.md:3: rewrap to 80 columns.
- Regenerate every stale FLOW.md, including those whose shared-file counts changed in batch 3.
- review-gate-record.md:38: wrap at "(from".
- plan.md "Resume a draft": add "Continue with [The growth loop](#the-growth-loop)."

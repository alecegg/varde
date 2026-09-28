---
type: reference
description: Defines Varde's three benchmark tiers, evidence, and limits.
generated: { by: codex/gpt-5.6, at: 2026-09-20T21:13:25Z }
paths:
  - .github/workflows/skills-benchmarks.yml
  - skills/tests/benchmark-foundation.sh
  - clis/learn/crates/varde-learn
  - tools/audit-word-counts.py
  - tests/word-count-audit-test.sh
schema_version: 1
artifact_type: reference
id: legacy-93882a9c500702a5
relationships: []
provenance:
  source: explicit-migration
  source_revision: 93882a9c500702a5
---

# Varde benchmark lifecycle

Use each tier for its distinct confidence level.

## Deterministic CI

Run `cd skills && tests/benchmark-foundation.sh` during ordinary CI.
GitHub runs it for skill pull requests and pushes.

Evidence is the command's exit status and fixture output.
Fixtures cover efficiency aggregation and changed-skill selection.

These checks use mocks and validate stable contracts.
They do not measure real agent quality.

## Instruction size audit

Run the word auditor before instruction refactors.
Pass both current and baseline skills directories.
List required and observed routing paths explicitly.

Physical words diagnose activated document size.
They never substitute for measured runtime tokens.
Keep entrypoint and reference totals separately visible.
Compare runtime quality after deterministic fixtures pass.

## Changed-skill release

Before releases, find skills changed since a base ref and run each by hand;
there is no changed-skills wrapper:

```bash
git diff --name-only <release-base> HEAD -- skills | cut -d/ -f2 | sort -u
```

For each name with both required files, run:

```bash
varde-learn eval output skills/<name>
```

Those files are `SKILL.md` and `evals/evals.json`.

Evidence lives under `<skill-dir>-workspace/iteration-<N>` by default.
`benchmark.json` records pass rates, timing, tokens, and deltas.
Run folders preserve transcripts, raw envelopes, grading, and timing.
Token efficiency reports successful assertions per thousand measured tokens.
Unavailable and measured-zero usage remain distinct states.

This tier requires `jq`, Claude CLI, and billable calls.
Its LLM judge provides evidence, not a release gate.
Completion exit status does not imply passing assertions.
Deterministic verifiers should accept equivalent valid phrasing.
Fixture observed transcript variants before widening matchers.

## Major-release lifecycle

Before major releases, run each scenario by hand in a disposable repository
with the skills and CLIs under evaluation installed. Save transcripts and
harness usage beside each scenario's evidence so releases stay comparable.

### `plan-build-verify`: Plan, build, and verify a bounded change

Setup:
- Prepare a disposable repository containing one bounded change request.
- Install the Varde skills and workflow CLI under evaluation.

Actions:
1. Create and finalize a plan with acceptance criteria.
2. Decompose the plan and execute every ready task sequentially.
3. Review the aggregate changes and verify every acceptance criterion.

Check:
- [ ] The finalized plan records explicit scope and acceptance criteria.
- [ ] Every task reaches done with verification evidence.
- [ ] The completed plan records verified acceptance criteria.

### `review-fix-verify`: Review, fix, and verify a seeded defect

Setup:
- Prepare a disposable repository containing one observable seeded defect.
- Capture the expected defect and regression check independently.

Actions:
1. Run a report-only review against the seeded change.
2. Apply the accepted finding through the review fix workflow.
3. Run the independent regression check.

Check:
- [ ] The review reports the seeded defect with concrete evidence.
- [ ] The fix changes only files required by the finding.
- [ ] The independent regression check passes afterward.

### `knowledge-record-recall`: Record and recall durable project knowledge

Setup:
- Prepare a disposable repository with one documented project decision.
- Remove that decision from the active conversation context.

Actions:
1. Record the decision through the knowledge workflow.
2. Start a fresh agent context.
3. Ask the agent to retrieve and apply the decision.

Check:
- [ ] The knowledge note preserves the decision and its rationale.
- [ ] The fresh context locates the correct knowledge note.
- [ ] The resulting recommendation follows the recorded decision.

## Related

- [Consolidated skill catalogue](/flows/consolidated-skill-catalogue.md) - identifies benchmarked skill surfaces.

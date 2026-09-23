---
type: reference
description: Defines Varde's three benchmark tiers, evidence, and limits.
generated: { by: codex/gpt-5.6, at: 2026-09-20T21:13:25Z }
paths:
  - .github/workflows/skills-benchmarks.yml
  - skills/tests/benchmark-foundation.sh
  - skills/varde-agent-doc-authoring/scripts/run-output-evals.sh
  - skills/varde-agent-doc-authoring/scripts/run-changed-output-evals.sh
  - skills/varde-change/scripts/audit-word-counts.py
  - skills/tests/word-count-audit.sh
  - skills/benchmarks/lifecycle-scenarios.json
  - skills/benchmarks/validate-lifecycle-scenarios.sh
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
Fixtures cover efficiency aggregation, changed-skill selection, and catalog validation.

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

Before releases, run this from the repository root:

```bash
skills/varde-agent-doc-authoring/scripts/run-changed-output-evals.sh \
  --base <release-base> --head HEAD
```

Only changed skills containing both required files qualify.
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

Before major releases, validate the scenario catalog:

```bash
skills/benchmarks/validate-lifecycle-scenarios.sh \
  skills/benchmarks/lifecycle-scenarios.json
```

Then manually execute every cataloged scenario.
Capture artifacts under each declared `evidence_paths` entry.
Capture harness usage under each declared token evidence path.

Current identifiers include `plan-build-verify` and `review-fix-verify`.
They also include `knowledge-record-recall`.
The catalog defines observable assertions and required evidence.

Validation checks catalog structure only.
No automated lifecycle runner currently executes these scenarios.
External-system comparisons wait until Varde fixtures stabilize.

## Related

- [Consolidated skill catalogue](/flows/consolidated-skill-catalogue.md) - identifies benchmarked skill surfaces.

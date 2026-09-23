---
type: reference
title: varde risk-triggered review specialists
---

# Varde risk-triggered review specialists

Unified review remains the default coordinator path.

## Routing

Derive explicit risk signals from changed files and review breadth.
Ordinary changes start no specialist. Risky changes start zero, one, or two
specialists, selected by fixed priority. The selector supports `security`,
`data-integrity`, `resilience`, `performance`, and `api-design`.

## Coordination

Specialists return candidate findings only. Each candidate includes location,
category, severity, evidence, impact, refutation attempts, and a suggested
disposition. The coordinator rejects malformed, unsupported, and duplicate
candidates, verifies the remaining evidence, and persists only unique findings.
Specialists never write review records directly.

## Related

- [Review routing](../../../skills/varde-review/references/report-routing.md)
- [Candidate contract](../../../skills/varde-review/references/report-candidates.md)

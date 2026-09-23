---
type: reference
title: varde change debugging entry
---

# Varde change debugging entry

Named bugs and regressions enter evidence-led debugging automatically.

## Routing precedence

Explicit intent wins. Review requests belong to `varde-review`. Exploration
requests belong to `varde-explore`. Diagnosis-only requests use
`debug_mode: diagnose`. Explicit build requests use the normal build path.
Only a bug or regression without explicit mode uses automatic
`debug_mode: fix` routing.

## Evidence order

Debugging records `route_source` as `automatic` or `explicit`. Its
`debug_evidence` progresses through reproduction, ranked hypotheses, tested
experiments, cause, and verification. Fixes require the first three fields
before source mutation. Completion requires cause and verification.

## Mutation boundary

Diagnosis-only work leaves production source unchanged. It reports uncertainty
when evidence cannot establish a cause. Fix work reruns the original
reproduction and the regression check before completion.

## Related

- [Debugging entry](../../../skills/varde-change/references/debugging-entry.md)
- [Debug posture](../../../skills/varde-change/references/build-posture-debug.md)

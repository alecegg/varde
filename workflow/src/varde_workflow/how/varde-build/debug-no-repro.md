---
topic: varde-build/debug-no-repro
version: 1
summary: Fallbacks when the bug cannot be reproduced locally or has no test seam
---

- Without local reproduction, name the attempts. Use a bounded trace
  or versioned source path labeled **unreproduced**, stating its origin and
  what it cannot establish. Separate observation from what the code suggests.
- Without either, stop and ask for the reproducing environment, an artifact,
  or permission to add temporary instrumentation.
- With no correct test seam, get pre-edit approval for an alternative that
  distinguishes fixed behavior from the defect. Otherwise stop and note the
  testability gap for the `refactor` posture.
- When the original scenario cannot run locally, use the independent
  verification approved in pre-edit review. Report the original symptom as
  unverified until checked in its environment.

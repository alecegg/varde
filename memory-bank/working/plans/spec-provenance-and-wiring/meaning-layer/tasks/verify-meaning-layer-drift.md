---
type: task
parent: spec-provenance-and-wiring/meaning-layer
status: done
verified: passed
depends_on:
  - generate-and-preserve-meaning-layer
modifies:
  - skills/varde-spec/references/VERIFY-AND-REPORT.md
creates: []
---

Verify meaning-layer drift

Extend the verification contract so every stored crux is checked as a literal
substring of at least one cited source. A mismatch must report its domain,
flow, and crux without failing the overall varde-spec run. Also check summary
uniqueness, typed link validity, and generated-boundary integrity.

#### Out of scope

- Changing generation behavior or source hashes.
- Treating meaning-layer drift as an error exit.

#### Verification

- assert: a controlled documented missing-crux example requires a report that names document and flow while retaining exit code 0 → requirement present
- assert: targeted `rg` checks in `skills/varde-spec/references/VERIFY-AND-REPORT.md` find cited-source substring drift, domain/flow reporting, non-fatal handling, summary, links, and boundary checks → each clause present
- retrieve: `skills/varde-spec/references/VERIFY-AND-REPORT.md` → verification contract remains compatible with manual reporting

#### Progress

- Defined non-fatal, literal crux-drift reporting with summary, link, and boundary checks.

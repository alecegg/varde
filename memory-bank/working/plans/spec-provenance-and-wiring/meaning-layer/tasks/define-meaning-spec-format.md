---
type: task
parent: spec-provenance-and-wiring/meaning-layer
status: done
verified: passed
depends_on: []
modifies:
  - skills/varde-spec/references/SPEC-FORMAT.md
creates: []
---

Define the generated meaning-layer document contract

Extend the generated domain-spec format with an explicit generated-block
boundary. Define exactly one document summary, typed domain wikilinks, and a
literal source crux inside every flow only. Preserve the byte-identical
hand-authored Notes tail below the generated block across regeneration.

Use paired HTML comment sentinels as the boundary. Require each crux to be an
exact substring of one cited `sources` file. Prohibit cruxes in tables, Scope
Boundary, Invariants, and Acceptance Criteria.

#### Out of scope

- Changing source provenance or varde-docs marker behavior.
- Implementing the generation or verification workflows.

#### Verification

- assert: targeted `rg` checks in `skills/varde-spec/references/SPEC-FORMAT.md` find the paired boundary, one-summary rule, typed wikilinks, literal cited-source crux, Flow-only placement, and preserved Notes tail → each clause present
- retrieve: `skills/varde-spec/references/SPEC-FORMAT.md` → contract reads as one coherent document format

#### Progress

- Defined generated boundaries, meaning content, Flow-only cruxes, and preserved Notes.

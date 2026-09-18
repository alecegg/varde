---
type: task
parent: spec-provenance-and-wiring/meaning-layer
status: done
verified: passed
depends_on:
  - define-meaning-spec-format
modifies:
  - skills/varde-spec/SKILL.md
creates: []
---

Generate and preserve the meaning layer

Update the generation workflow to use the existing `sources` list and
`includeBody` symbol bodies. It must select a literal guard, skip condition, or
state-change crux from those bodies, render the summary, typed links, and flow
crux in the generated block, and replace only that block during regeneration.
The Notes tail must survive byte-for-byte. Do not introduce a separate source
read, modify provenance, or commit generated specifications.

#### Out of scope

- Changing the document-format contract beyond needed execution guidance.
- Implementing drift verification.

#### Verification

- assert: a fixture-style shell walkthrough with a source body and generated document proves the regenerated Notes tail checksum matches its pre-run checksum → identical
- assert: targeted `rg` checks in `skills/varde-spec/SKILL.md` require existing sources, `includeBody` literal crux selection, generated-block-only replacement, and no generated-spec commits → each requirement present
- retrieve: `skills/varde-spec/SKILL.md` → generation workflow remains consistent with its existing isolated-run rules

#### Progress

- Documented source-body crux generation and byte-preserved Notes replacement; fixture and contract checks passed.

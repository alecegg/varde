---
slug: concept
type: definition
definition: >-
  A single unit of knowledge within a Knowledge Bundle — a markdown file
  with YAML frontmatter. By default only base structural correctness is
  validated (parses as markdown + frontmatter). Full OKF v0.2 §2
  conformance (e.g. a `type` field, plus optional trust/lifecycle/
  provenance/computation fields per the spec) is an optional, opt-in
  attribute checked via `lint --okf`, not enforced on write.
avoid:
  - note
---

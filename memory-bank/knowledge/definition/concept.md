---
slug: concept
type: definition
definition: >-
  A single unit of knowledge within a Knowledge Bundle — a markdown file
  with YAML frontmatter. `lint_base` validates only structural correctness
  (parses as markdown + frontmatter, valid UTF-8, kebab-case slug, no path
  traversal); a `type` field plus optional trust/lifecycle/provenance/
  computation fields are conventional, not enforced by the base lint.
avoid:
  - note
---

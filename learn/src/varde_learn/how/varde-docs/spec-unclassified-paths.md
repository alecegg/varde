---
topic: varde-docs/spec-unclassified-paths
version: 1
summary: Report and classify unclassified and overlapping source paths
---

Report these on every run, including scoped runs:

- current source candidates (workspace members, source directories,
  entrypoints, deployment declarations) outside all domain `source_roots`;
- candidates covered by more than one domain root;
- architecture overlap with domains, without changing a domain boundary.

Inspect each `unclassified_paths` entry before classifying it as a new domain
source, an architecture declaration, or unrelated; an unrecognized extension
does not make it unrelated.

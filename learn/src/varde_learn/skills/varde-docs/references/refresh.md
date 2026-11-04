# Refresh user-facing documentation

## Outcomes

- Scope: the named file only; otherwise `README.md`, `docs/*.md`, and existing
  CHANGELOG and release notes of the current module (the Git root outside a
  module). A cross-module request adds each named or touched module's documents.
- Read each document in scope in full and compare it with the source its
  subject describes (and any spec under `<knowledge>/specs/` for that area).
  Fix stale paths, removed or renamed operations, contradicted invariants, and
  missing source concepts. Keep hand-written sections the source does not
  contradict.
- A direct refresh applies source-grounded changes in place and shows a
  per-document summary and diff. A proposal, review, or preview request shows
  the diff without writing. Ask the user only for unresolved factual or product
  choices.
- Edited documents are verified against their source. Source-path references
  within scope are repaired when the correct path is established and verified
  again; paths whose replacement remains uncertain are reported.

## Constraints

- Edit documents one at a time; delegate only independent documents, to at most
  three delegates.
- Use `varde map context_pack` (see `references/varde-code-cli.md`) to map each
  document to its source.
- Curate release notes from completed changes; don't infer a release from a
  draft plan.
- Diagrams in Mermaid only.

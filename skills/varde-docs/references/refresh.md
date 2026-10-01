# Refresh user-facing documentation

## Workflow

1. **List the documents:**
   - Given `docPath`, list only that file.
   - Otherwise list `README.md`, `docs/*.md`, and existing CHANGELOG and release
     notes of the current module (or the Git root outside a module).
   - For a cross-module request, also list each named or touched module's
     documents.
2. Many `docs/` files and `varde-code` on PATH → load
   `references/varde-code-cli.md` and `references/code-lookups.md`;
   `varde-code context_pack --json '{"repoRoot":"<repo>","query":"<doc subject>"}'`
   maps each doc to source.
3. **Edit each document** one at a time, or with up to three delegates for
   independent documents, given absolute `<working>`/`<knowledge>` paths:
   1. Read it in full, then the source its subject describes and any spec
      under `<knowledge>/specs/` for that area.
   2. Compare with source facts (stale paths, removed or renamed operations,
      contradicted invariants, source concepts missing from the doc), keeping
      hand-written sections the source does not contradict.
4. **Apply or propose:** for a direct refresh, apply source-grounded changes
   in place and show a per-document summary and diff; for a proposal, review,
   or preview request, show the diff without writing. Ask the user only for
   unresolved factual or product choices.
5. **Verify edited documents** against their source. Repair source-path
   references within scope when the correct path is established and verify
   again; report paths whose replacement remains uncertain.
6. **Record lessons:** real obstacles through `varde-learn`; skip otherwise.

## Constraints

- Curate release notes from completed changes; don't infer a release from a
  draft plan.
- Diagrams in Mermaid only.

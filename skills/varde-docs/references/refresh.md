# Refresh user-facing documentation

Keep README.md, docs/*.md, CHANGELOGs, and release notes accurate for the
current code. Curate release notes from completed changes; don't infer a
release from a draft plan.

## Workflow

1. **List the documents.** For `docPath`, use only that document. Otherwise,
   use the current module when invoked inside one, or the Git root when no
   module applies. Include its `README.md`, `docs/*.md`, and existing CHANGELOG
   and release notes. For a request spanning modules, include those documents
   from each named or touched module. Memory paths are resolved at first use
   below; document scope never changes memory storage.
2. Many `docs/` files and `varde-code` on PATH → load
   `references/varde-code.md` for watcher readiness and source fallback, then
   `varde-code context_pack --json '{"repoRoot":"<repo>","query":"<doc subject>"}'`
   maps each doc to source.
3. **Edit directly requested documents,** one document at a time; at most three delegates, for
   independent documents only. Before delegating memory-dependent work, resolve
   paths once as below and pass absolute `<working>`/`<knowledge>` paths;
   delegates reuse them without re-resolving. For each
   document:
   1. Read it in full, then read the source its subject describes, plus any
      spec under `<knowledge>/specs/` for that area. Before that lookup,
      resolve memory paths once with `varde-workflow paths --json` at the Git
      root, following the entry-point resolution/failure rules; reuse paths
      already supplied by the caller. A task that does not look up specs or
      record lessons needs no memory lookup.
   2. Compare with source facts: stale paths, removed or renamed operations,
      contradicted invariants, concepts in the source missing from the doc.
      Preserve hand-written sections unless the source contradicts them.

   For a direct refresh request, apply source-grounded changes in place and
   show a concise per-document summary and diff. For an explicit proposal,
   review, or preview request, show the proposed diff without writing it.
   Ask the user only for unresolved factual or product choices.
4. **Verify edited documents** against the source they describe; repair
   source-path references within the requested scope when the correct path
   is established, then verify again. Report paths whose replacement remains
   uncertain.
5. **Record lessons.** Record real obstacles through `varde-learn` and durable
   decisions through `varde-knowledge`. Resolve memory paths at first use if
   still unresolved; otherwise reuse them. Skip when there are no lessons.

## Constraints

- Diagrams in Mermaid only.

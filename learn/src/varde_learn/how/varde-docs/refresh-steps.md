---
topic: varde-docs/refresh-steps
version: 1
summary: Refresh docs - part 1 of 2 (steps 1-3) - preview or proposal must not write; load part 2 first
---

# Refresh documents: steps 1-3

1. **List the documents:**
   - Given a named file, list only that file.
   - Otherwise list `README.md`, `docs/*.md`, and existing CHANGELOG and release
     notes of the current module (or the Git root outside a module).
   - For a cross-module request, also list each named or touched module's
     documents.
2. Load `references/varde-code-cli.md`;
   `varde map context_pack --json '{"repoRoot":"<repo>","query":"<doc subject>"}'`
   maps each doc to source; use `get_symbol`/`batch` for exact bodies and
   related lookups.
3. **Edit each document** one at a time, or give independent ones to up to
   three delegates with absolute `<working>`/`<knowledge>` paths.
   1. Read it in full, then the source its subject describes and any spec
      under `<knowledge>/specs/` for that area.
   2. Compare with source facts (stale paths, removed or renamed operations,
      contradicted invariants, source concepts the doc lacks), keeping
      hand-written sections the source does not contradict.

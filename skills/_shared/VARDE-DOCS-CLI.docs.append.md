## Operations

This skill touches two corpora, both reachable as `varde-docs` bundles.
Fall back to Read/Grep/Write/Edit on any failure. Paths are relative to the
effective `repoRoot` from step 1 (the current checkout by default, or a
worktree path if step 1 isolated for a concurrent-edit risk).

**Generated specs (read).** When refreshing spec-declared sections (Phase 0)
and proposing edits, read the specs bundle instead of Grep/Read:

```bash
varde-docs concept show   --bundle memory-bank/knowledge specs/<domain> --json
varde-docs concept search --bundle memory-bank/knowledge --field type=spec --text "<query>" --json
```

**README + `docs/*.md` (read/write).** README.md is slug `README` in bundle
`.`; a doc `docs/foo.md` is slug `foo` in bundle `docs`.

```bash
# Discovery / drift hunt (Phase 1, Phase 3): ranked full-text instead of a
# manual read of every doc/source pair.
varde-docs concept search --bundle docs --text "<feature/term>" --json
varde-docs concept show   --bundle docs foo --json    # whole doc + "version"

# Whole-file write (a full-doc regenerate or an approved proposal): OCC update.
varde-docs concept update --bundle docs foo --expected-version <version> --file "${TMPDIR:-/tmp}/doc.md"
```

Caveats:

- **Section-scoped rewrites stay Edit.** The auto-generate track rewrites only
  the blocks inside a freshness marker; the CLI writes at whole-file
  granularity and can't touch just one marked section. Use the CLI for
  whole-doc `show`/`search` and full-file writes; keep Edit for in-place
  marker-block rewrites (`references/PHASE-2-AUTOGENERATE.md`).
- **Plain docs may have no frontmatter** — that's fine (`create` requires no
  `type`; OCC hashes the whole file). `--field`/`lint` just have less to work
  with on frontmatter-less docs; `--text` search still applies.
- **OCC clobber-protection is load-bearing in the default checkout.** Since
  this skill usually runs in the current checkout (not a worktree), a
  concurrent edit is possible — the `--expected-version` check catches it. Its
  other wins are ranked `search` discovery and uniform whole-doc reads.

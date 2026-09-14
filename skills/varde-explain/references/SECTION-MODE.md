# Section mode

Trigger: target is a feature-area keyword or a file/directory path.

- **Keyword target** — when `varde-code` is available
  (`references/VARDE-CODE-CLI.md`), run `context_pack` for the keyword
  first — it returns matching files/symbols, their one-hop neighborhood,
  and covering tests in one call. Otherwise use `Grep`/`Glob` to locate
  files, symbols, and tests matching the keyword (e.g. search for the term
  across `src/`, check directory names, look for related test files). Use
  what surfaces as the primary context, then `Read`/`get_symbol` those
  files directly.
- **Path target** — run the proactive gathering directly on the specified
  file or directory's source files. When `varde-code` is available, use
  `symbols_in_file`/`symbols_in_files` (`includeBody`) in place of
  Glob-then-Read. Otherwise: `Glob` to enumerate files, `Grep` for symbol
  references and importers, `Read` for the actual contents.
- **Git history** — run `git log --oneline -20 <path>` on the target for
  historical context; feed notable commits into the Background section.

Proceed to write the HTML output (workflow step 4).

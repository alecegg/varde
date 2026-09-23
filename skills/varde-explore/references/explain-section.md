# Area explanation

Use when the target is a feature-area keyword or a file/directory path.

- **Keyword target** — If `varde-code` is available
  (`references/varde-code.md`), run `context_pack` for the keyword first. It
  returns matching files/symbols, their one-hop neighborhood, and covering
  tests in one call. If it is unavailable, use `Grep`/`Glob` to locate files,
  symbols, and tests matching the keyword (for example, search across `src/`,
  check directory names, and look for related test files). Treat those results
  as primary context. Then `Read`/`get_symbol` the files directly.
- **Path target** — Read the specified file or directory directly. When
  one exact symbol sits inside a large file, use `get_symbol`. Load Varde Code
  for unknown directory scope, importers, or relationships. Batch related
  lookups. Otherwise, use `Glob`, `Grep`, and direct reads.
- **Git history** — Run `git log --oneline -20 <path>` on the target. Add
  notable commits to the Background section.

Write the HTML output by following workflow step 4.

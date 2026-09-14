# Using scripts in skills (agentskills.io)

## One-off commands (no `scripts/` needed)

When an existing package already does the job, reference it directly in `SKILL.md` via an auto-resolving runner instead of bundling anything:

- `uvx ruff@0.8.0 check .` (Python, via uv; not bundled, fast/cached)
- `pipx run 'black==24.10.0' .` (Python; mature alternative to uvx)
- `npx eslint@9 --fix .` (ships with Node.js)
- `bunx eslint@9 --fix .` (Bun's npx equivalent — only if the env has Bun)
- `deno run --allow-read npm:eslint@9 -- --fix .` (needs explicit permission flags)
- `go run golang.org/x/tools/cmd/goimports@v0.28.0 .` (built into `go`)

Tips: **pin versions** so behavior doesn't drift; **state prerequisites** in `SKILL.md` prose, and use the `compatibility` frontmatter field for runtime-level requirements ("Requires Node.js 18+"); once a command grows complex enough to be hard to get right on the first try, move it into a tested script instead.

## Referencing bundled scripts

Use relative paths from the skill directory root (the agent runs commands from there) — no absolute paths. List them explicitly in `SKILL.md` so the agent knows they exist:

```markdown
## Available scripts

- A validator script can validate configuration files.
- A processor script can transform input data.
```

Then give the bundle's exact invocation steps.

## Self-contained scripts (own dependencies, no separate install step)

- **Python**: PEP 723 inline metadata block, run with `uv run scripts/extract.py` (or `pipx run`):
  ```python
  # /// script
  # dependencies = ["beautifulsoup4"]
  # ///
  ```
  Pin with PEP 508 specifiers (`"beautifulsoup4>=4.12,<5"`), constrain via `requires-python`, lock with `uv lock --script`.
- **Deno**: `npm:`/`jsr:` import specifiers make scripts self-contained by default; `deno run scripts/extract.ts`. Native-addon npm packages may not work.
- **Bun**: auto-installs on run when no `node_modules` exists; pin versions in the import path itself (`import * as cheerio from "cheerio@1.0.0"`).
- **Ruby**: `bundler/inline` with a `gemfile do ... end` block; pin gem versions since there's no lockfile. A stray `Gemfile`/`BUNDLE_GEMFILE` in the working dir can interfere.

## Designing scripts for agentic use

- **No interactive prompts** — agents run in non-interactive shells and cannot answer TTY prompts; a blocking prompt hangs forever. Accept everything via flags/env/stdin, and fail with a message telling the agent what flag to pass instead.
- **`--help` output** is the primary interface doc an agent reads — keep it concise (it enters context): description, flags, 1-2 usage examples.
- **Helpful error messages**: state what went wrong, what was expected, what to try — not "Error: invalid input."
- **Structured output** (JSON/CSV/TSV) over whitespace-aligned text, so both the agent and `jq`/`awk` can consume it. Send data to stdout, diagnostics/progress/warnings to stderr, so the agent can capture clean parseable output while still seeing diagnostics.
- **Idempotency**: agents may retry — "create if not exists" beats "create and fail on duplicate."
- **Closed input sets**: reject ambiguous input with a clear error rather than guessing.
- **`--dry-run`** for destructive/stateful operations.
- **Meaningful, documented exit codes** per failure type (not found / invalid args / auth failure).
- **Safe defaults for destructive ops** — consider requiring `--confirm`/`--force`.
- **Predictable output size**: harnesses often truncate tool output past ~10-30K chars. Default to a summary, support `--offset`/pagination, or require an explicit `--output <file|->` flag for large output instead of dumping to stdout by default.

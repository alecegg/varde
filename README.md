# varde

A monorepo for the `varde` family: the agent-facing skills and the two Rust CLIs they light up. Each top-level folder is a **self-contained module** with its own build, dependencies, and docs — they are combined here for one-clone, atomic-change convenience, not merged into a single build. See [AGENTS.md](AGENTS.md) for the module convention.

| Folder | Package / name | What it is |
|---|---|---|
| [`skills/`](skills/) | `varde-*` skills | The `varde-*` Claude/opencode skills that drive the plan → build → review → document lifecycle. Work standalone; light up extra capability when the two CLIs are on `PATH`, with graceful fallback to plain file operations when absent. |
| [`agents/`](agents/) | `varde` agents | Installable subagent definitions (plan / build / review / explore) that wrap the skills, with one variant per harness (Claude / Codex / opencode). Installed via `agents/install.sh`, the same model as `skills/`. |
| [`code-cli/`](code-cli/) | `varde-code` | A native Rust code-intelligence engine (tree-sitter parsing, entity/symbol extraction, SQLite-backed query/scan), exposed as a single `varde-code` CLI. Skills use it for code queries and scans; without it they fall back to grep/glob. |
| [`docs-cli/`](docs-cli/) | `varde-docs`, `okf-core`, `docwatch` | A standalone Rust CLI for a generic markdown-with-frontmatter knowledge store (ranked search, uniform CRUD, optimistic-concurrency writes, lint). Skills use it for knowledge notes, specs, plans, and docs; without it they fall back to Read/Write/Edit. |

## Working in this repo

Each module builds and tests on its own — there is no root build:

```bash
cd code-cli && cargo build         # varde-code CLI
cd docs-cli && cargo build         # varde-docs / okf-core / docwatch
cd skills   && ./install.sh        # install varde-* skills into ~/.claude/skills
cd agents   && ./install.sh        # install varde agents into ~/.claude/agents
```

Refer to each folder's own `README.md` and `AGENTS.md`/`CLAUDE.md` for details.

## License

All modules share the same license — see [LICENSE](LICENSE).

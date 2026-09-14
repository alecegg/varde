# varde

`varde` is a family of tools for agent-assisted software work.
It combines reusable workflow skills, installable subagents, and Rust CLIs
for code intelligence and knowledge management.

This repository is a monorepo for convenience, not a unified application.
Every top-level folder is a self-contained module with its own dependencies,
build commands, and documentation. There is no root build or test command.

See [AGENTS.md](AGENTS.md) for the repository conventions used by contributors
and coding agents.

## Choose a module

| Module | Use it when | Main deliverable |
|---|---|---|
| [`skills/`](skills/README.md) | You want agent workflows for planning, building, reviewing, documenting, and related work. | `varde-*` skills for Claude and opencode. |
| [`agents/`](agents/README.md) | You want ready-made plan, build, review, and exploration subagents. | Harness-specific agent definitions for Claude, Codex, and opencode. |
| [`code-cli/`](code-cli/README.md) | You need local symbol extraction, code queries, structural search, or scans. | The `varde-code` CLI. |
| [`docs-cli/`](docs-cli/README.md) | You need a generic markdown knowledge store or document-triggered agent orchestration. | The `varde-docs`, `okf-core`, and `docwatch` workspace. |

The modules are intentionally independent. Do not add cross-folder source
imports, path dependencies, or a root `Cargo.toml`. Skills can use the CLIs
only when their installed binaries are available on `PATH`; otherwise, they
fall back to ordinary file operations.

## Quick start

Install the module that matches your needs. Each module README is the
authoritative installation and usage guide.

### Workflow skills

Install all skills for Claude, or select a different skills directory:

```sh
cd skills
./install.sh
./install.sh -d ~/.config/opencode/skills
./install.sh -s varde-plan,varde-review
```

Run `./install.sh -h` for every installer option. The skills cover the full
workflow, including planning, implementation, review, documentation, and
handoff activities. See the [skills README](skills/README.md) for the full
skill list and trigger guidance.

### Subagents

Install all agents for the current harness, or choose a supported harness:

```sh
cd agents
./install.sh
./install.sh -t codex
./install.sh -t opencode -a plan,review
```

The available agents are `plan`, `build`, `review`, and `explore`. They use
the installed `varde-*` skills, so install the skills first. See the
[agents README](agents/README.md) for harness-specific installation details.

### Code intelligence

`varde-code` indexes a repository locally, then exposes symbol, dependency,
hotspot, mapping, pattern-search, and rule-scan queries through one CLI.
Build it from this module with Cargo:

```sh
cd code-cli
cargo build
cargo test
cargo install --path crates/varde-code
```

After installation, build an index and query it:

```sh
varde-code build --repo-root .
varde-code hotspots --json '{"repoRoot":"."}'
```

See the [code CLI README](code-cli/README.md) for supported languages,
installation releases, query commands, and architecture documentation.

### Knowledge tools

The `docs-cli` workspace provides three components:

- `okf-core`, the library for OKF concept and bundle operations.
- `varde-docs`, the CLI for creating, reading, searching, updating, and
  linting markdown knowledge bundles.
- `docwatch`, a macOS-oriented watcher that dispatches an agent for unresolved
  trigger tags in Markdown files.

Build and test this workspace locally:

```sh
cd docs-cli
cargo build
cargo test
```

`docs-cli` is pre-alpha. Its detailed [README](docs-cli/README.md) documents
the OKF workflow, command syntax, vault layering, and `docwatch` lifecycle.

## Development workflow

Work within the module you change. Run commands from that folder, use its
local instructions, and keep changes inside that module unless a coordinated
repository-level documentation update is needed.

| Module | Build | Test | Install |
|---|---|---|---|
| `skills/` | Not applicable | `./install.sh -h` | `./install.sh` |
| `agents/` | Not applicable | `./install.sh -h` | `./install.sh` |
| `code-cli/` | `cargo build` | `cargo test` | `cargo install --path crates/varde-code` |
| `docs-cli/` | `cargo build` | `cargo test` | Build outputs include `varde-docs` and `docwatch` |

The Rust modules are separate Cargo workspaces. Run `cargo build` and
`cargo test` in the appropriate module, never from the repository root.
Their local `AGENTS.md` or `CLAUDE.md` files may add module-specific rules.

## Repository layout

```text
varde/
├── skills/      Reusable varde-* agent workflow skills
├── agents/      Installable harness-specific subagent definitions
├── code-cli/    Rust workspace for varde-code
└── docs-cli/    Rust workspace for varde-docs, okf-core, and docwatch
```

## Documentation

Use the module documentation for implementation details:

- [Skills guide](skills/README.md)
- [Agents guide](agents/README.md)
- [varde-code guide](code-cli/README.md)
- [varde-docs guide](docs-cli/README.md)
- [Repository contributor instructions](AGENTS.md)

## License

All modules share the [MIT License](LICENSE).

# varde

`varde` is a family of tools for agent-assisted software work.
It combines reusable workflow skills, installable subagents, and Rust CLIs
for code intelligence and knowledge management.

This repository is a monorepo for convenience, not a unified application.
Every top-level folder is a self-contained module with its own dependencies,
build commands, and documentation. There is no root build or test command.

Use `varde init` to wire supported agent harnesses. It delegates to the
existing skills and agents installers. It does not build or test modules.

See [AGENTS.md](AGENTS.md) for the repository conventions used by contributors
and coding agents.

## Choose a module

| Module | Use it when | Main deliverable |
|---|---|---|
| [`skills/`](skills/README.md) | You want agent workflows for planning, building, reviewing, documenting, and related work. | `varde-*` skills for Claude, Codex, and opencode. |
| [`agents/`](agents/README.md) | You want ready-made plan, execution, review, and exploration subagents. | Harness-specific agent definitions for Claude, Codex, and opencode. |
| [`code-cli/`](code-cli/README.md) | You need local symbol extraction, code queries, structural search, or scans. | The `varde-code` CLI. |
| [`workflow-cli/`](workflow-cli/README.md) | You need a generic markdown knowledge store or document-triggered agent orchestration. | The `varde-workflow`, `okf-core`, and `docwatch` workspace. |

The modules are intentionally independent. Do not add cross-folder source
imports, path dependencies, or a root `Cargo.toml`. Skills can use the CLIs
only when their installed binaries are available on `PATH`; otherwise, they
fall back to ordinary file operations.

## Quick start

Install the module that matches your needs. Each module README is the
authoritative installation and usage guide.

### Wire supported harnesses

Run the root entry point from this checkout:

```sh
./varde init --dry-run
./varde init --yes
```

It detects Claude, Codex, and opencode configurations. Use `--agents` to
choose harnesses explicitly, or `--list-agents` to print their identifiers:

```sh
./varde init --agents codex
./varde init --list-agents
```

The command only delegates installation. Module READMEs remain authoritative
for installer options and development. Installed skill descriptions remain the
authoritative routing surface.

Varde installs seven user-facing skills by default:

| Skill | Primary intent |
|---|---|
| `varde-explore` | Exploration and rich code explanation |
| `varde-change` | Planning, building, verification, and conclusion |
| `varde-review` | Review reports and explicit improvement modes |
| `varde-docs` | User documentation and generated specifications |
| `varde-knowledge` | Durable knowledge, friction, and handoffs |
| `varde-prototype` | Throwaway visual and logic prototypes |
| `varde-agent-doc-authoring` | Instructions and references for agents |

Natural language selects each skill and internal mode.
Ask for exploration before choosing implementation direction.
Request explanation when learning how a module works.
Use planning before uncertain or multi-part changes.
Use building after scope and acceptance criteria settle.
Request review for report-only findings across changed code.
Record knowledge when decisions must outlive one session.

Project knowledge lives under each module's `memory-bank/knowledge/` folder.
It is reviewed and committed like source. Plans, reviews, journals, and task
evidence stay local under `memory-bank/working/`. Personal knowledge remains
outside this repository.

### Workflow skills

Install all skills for Claude, or select a different skills directory:

```sh
cd skills
./install.sh
./install.sh -d ~/.config/opencode/skills
./install.sh -s varde-change,varde-review
```

Optional capability packs stay outside the seven-skill core:

```sh
./install.sh --pack browser
./install.sh --pack shipping
./install.sh --pack diagnostics
```

The browser pack adds report-only validation guidance. The shipping pack adds
release guidance. The diagnostics pack analyzes Varde sessions. See the
[skills README](skills/README.md) for their scope and installation options.

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

The available agents are `plan`, `executor`, `review`, and `explore`. They use
generated Claude, Codex, and OpenCode adapters. Install the skills first. See the
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

After installation, query a repository directly. Build remains optional:

```sh
varde-code hotspots --json '{"repoRoot":"."}'
varde-code build --repo-root .
```

See the [code CLI README](code-cli/README.md) for supported languages,
installation releases, query commands, and architecture documentation.

### Knowledge tools

The `workflow-cli` workspace provides three components:

- `okf-core`, the library for OKF concept and bundle operations.
- `varde-workflow`, the CLI for creating, reading, searching, updating, and
  linting markdown knowledge bundles.
- `docwatch`, a macOS-oriented watcher that dispatches an agent for unresolved
  trigger tags in Markdown files.

Build and test this workspace locally:

```sh
cd workflow-cli
cargo build
cargo test
```

`workflow-cli` is pre-alpha. Its detailed [README](workflow-cli/README.md) documents
the OKF workflow, command syntax, vault layering, and `docwatch` lifecycle.

## Development workflow

Work within the module you change. Run commands from that folder, use its
local instructions, and keep changes inside that module unless a coordinated
repository-level documentation update is needed.

| Module | Build | Test | Install |
|---|---|---|---|
| `skills/` | Not applicable | `./check-refs.sh && for test_file in tests/*.sh; do "$test_file"; done` | `./install.sh` |
| `agents/` | `./generate.py --check` | `./test-consolidated-skills.sh` | `./install.sh` |
| `code-cli/` | `cargo build` | `cargo test` | `cargo install --path crates/varde-code` |
| `workflow-cli/` | `cargo build` | `cargo test` | Build outputs include `varde-workflow` and `docwatch` |

The Rust modules are separate Cargo workspaces. Run `cargo build` and
`cargo test` in the appropriate module, never from the repository root.
Their local `AGENTS.md` or `CLAUDE.md` files may add module-specific rules.

## Repository layout

```text
varde/
├── skills/      Reusable varde-* agent workflow skills
├── agents/      Installable harness-specific subagent definitions
├── code-cli/    Rust workspace for varde-code
└── workflow-cli/    Rust workspace for varde-workflow, okf-core, and docwatch
```

## Documentation

Use the module documentation for implementation details:

- [Skills guide](skills/README.md)
- [Agents guide](agents/README.md)
- [varde-code guide](code-cli/README.md)
- [varde-workflow guide](workflow-cli/README.md)
- [Repository contributor instructions](AGENTS.md)

## License

All modules share the [MIT License](LICENSE).

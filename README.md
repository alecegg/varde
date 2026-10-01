# varde

`varde` is a family of tools for agent-assisted software work.
It combines reusable workflow skills, installable subagents, and Rust CLIs
for code intelligence, markdown workflows, skill evaluations, and friction.

This repository is a monorepo for convenience, not a unified application.
The `skills/` and `agents/` folders and each workspace under `clis/` are
self-contained modules with their own dependencies,
build commands, and documentation. There is no root build or test command.

Use `varde sync` to install the four CLIs and wire supported agent harnesses.
It delegates to the existing skills and agents installers and runs `varde-toz install`
for each selected harness. It does not run module tests.

See [AGENTS.md](AGENTS.md) for the repository conventions used by contributors
and coding agents.

## Choose a module

| Module | Use it when | Main deliverable |
|---|---|---|
| [`skills/`](skills/README.md) | You want agent workflows for planning, building, reviewing, documenting, and related work. | `varde-*` skills for Claude, Codex, and opencode. |
| [`agents/`](agents/README.md) | You want ready-made plan, execution, review, and exploration subagents. | Harness-specific agent definitions for Claude, Codex, and opencode. |
| [`clis/code/`](clis/code/README.md) | You need local symbol extraction, code queries, structural search, or scans. | The `varde-code` CLI. |
| [`clis/workflow/`](clis/workflow/README.md) | You need a generic markdown knowledge store. | The `varde-workflow` and `varde-workflow-core` workspace. |
| [`clis/toz/`](clis/toz/README.md) | You need to keep large tool output out of an agent's context window. | The `varde-toz` (tool-output-zone) CLI. |
| [`clis/learn/`](clis/learn/README.md) | You need skill evaluations or the global friction store. | The `varde-learn` CLI. |

The modules are intentionally independent. Do not add cross-folder source
imports, path dependencies, or a root `Cargo.toml`. Skill instructions name
their CLI fallbacks. Friction recording through `varde-learn` requires its
CLI; if it is unavailable or fails, report that the event was not recorded and
do not write a Markdown fallback.

## Quick start

Install the module that matches your needs. Each module README is the
authoritative installation and usage guide.

### Wire supported harnesses

Run the root entry point from this checkout:

```sh
./varde sync --dry-run
./varde sync --yes
```

It copies the skills into `~/.agents/skills`, links each harness's skills
directory to those copies, installs the agents, and removes retired skills it
installed. It detects Claude, Codex, and opencode configurations. Use `--agents` to
choose harnesses explicitly, or `--list-agents` to print their identifiers:

`varde-review` is a harness skill, not a terminal command. The installer makes
it available by installing its `SKILL.md` and references into the shared skills
directory and linking it into each selected harness.

```sh
./varde sync --agents codex
./varde sync --list-agents
```

Use `--skills-dir` and `--agents-dir`/`--agent-format` to install into a
harness this repository does not auto-detect. Both flags are repeatable and
not persisted between runs; pass them again on the next `./varde sync`. When
given without `--agents`, they replace detection instead of adding to it. For
example, to install the skills for pi:

```sh
./varde sync --skills-dir ~/.pi/agent/skills
```

### Upgrade

`varde sync` installs the CLIs and harness files from this checkout; rerun it
after pulling:

```sh
git pull
./varde sync --yes
```

The command only delegates installation. Module READMEs remain authoritative
for installer options and development. Installed skill descriptions remain the
authoritative routing surface.

Varde installs ten user-facing skills by default:

| Skill | Primary intent |
|---|---|
| `varde-explore` | Exploration and rich code explanation |
| `varde-change` | Planning, building, verification, and conclusion |
| `varde-review` | Review reports and explicit improvement modes |
| `varde-docs` | User documentation and generated specifications |
| `varde-knowledge` | Durable knowledge notes and handoffs |
| `varde-learn` | Real friction capture, reconciliation, distillation, and skill evaluations |
| `varde-prototype` | Throwaway visual and logic prototypes |
| `varde-agent-doc-authoring` | Instructions and references for agents |
| `varde-manage` | Installation, configuration, and rule setup |
| `varde-toz` | Query and analyze captured tool output |

Natural language selects each skill and internal mode.
Ask for exploration before choosing implementation direction.
Request explanation when learning how a module works.
Use planning before uncertain or multi-part changes.
Use building after scope and acceptance criteria settle.
Request review for report-only findings across changed code.
Record knowledge when decisions must outlive one session.

Project knowledge lives in the root `memory-bank/knowledge/` bundle and is
reviewed and committed like source. Plans, reviews, journals, and task evidence
live in the configured working store (`varde-workflow paths --json`). We recommend
keeping that store outside source repositories, under a shared root with distinct
project folders, preferably in a separate Git repository or storage with version
history. See the [recommended setup](skills/varde-manage/references/setup.md#recommended-working-memory-setup).
Personal knowledge remains outside this repository.

### Workflow skills

Install all skills for Claude, or select a different skills directory:

```sh
cd skills
./install.sh
./install.sh -d ~/.config/opencode/skills
./install.sh -s varde-change,varde-review
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
./install.sh -t opencode -a varde-planner,varde-reviewer
```

The available agents are `varde-planner`, `varde-executor`, `varde-reviewer`, and `varde-explorer`. They use
generated Claude, Codex, and OpenCode adapters. Install the skills first. See the
[agents README](agents/README.md) for harness-specific installation details.

### Code intelligence

`varde-code` indexes a repository locally, then exposes symbol, dependency,
hotspot, mapping, pattern-search, and rule-scan queries through one CLI.
Build it from this module with Cargo:

```sh
cd clis/code
cargo build
cargo test
cargo install --path crates/varde-code
```

After installation, query a repository directly. Build remains optional:

```sh
varde-code hotspots --json '{"repoRoot":"."}'
varde-code build --repo-root .
```

See the [code CLI README](clis/code/README.md) for supported languages,
installation releases, query commands, and architecture documentation.

### Knowledge tools

The `workflow` workspace provides two components:

- `varde-workflow-core`, the library for concept and bundle operations.
- `varde-workflow`, the CLI for creating, reading, searching, updating, and
  linting markdown knowledge bundles.

Build and test this workspace locally:

```sh
cd clis/workflow
cargo build
cargo test
```

`workflow` is pre-alpha. Its detailed [README](clis/workflow/README.md) documents
the workflow, command syntax, and knowledge-bundle layout.

## Development workflow

Work within the module you change. Run commands from that folder, use its
local instructions, and keep changes inside that module unless a coordinated
repository-level documentation update is needed.

| Module | Build | Test | Install |
|---|---|---|---|
| `skills/` | Not applicable | `./check-refs.sh && for test_file in tests/*.sh; do "$test_file"; done` | `./install.sh` |
| `agents/` | `./generate.py --check` | `./test-consolidated-skills.sh` | `./install.sh` |
| `clis/code/` | `cargo build` | `cargo test` | `cargo install --path crates/varde-code` |
| `clis/workflow/` | `cargo build` | `cargo test` | Build outputs include `varde-workflow` |
| `clis/toz/` | `cargo build` | `cargo test --workspace` | `cargo install --path crates/toz --locked` |
| `clis/learn/` | `cargo build --workspace` | `cargo test --workspace` | `cargo install --path crates/varde-learn` |

The Rust modules are separate Cargo workspaces. Run `cargo build` and
`cargo test` in the appropriate module, never from the repository root.
Their local `AGENTS.md` or `CLAUDE.md` files may add module-specific rules.

## Repository layout

```text
varde/
├── skills/          Reusable varde-* agent workflow skills
├── agents/          Installable harness-specific subagent definitions
└── clis/            Independent Rust workspaces
    ├── code/        varde-code
    ├── workflow/    varde-workflow and varde-workflow-core
    ├── toz/         varde-toz (tool-output-zone)
    └── learn/       varde-learn
```

## Documentation

Use the module documentation for implementation details:

- [Skills guide](skills/README.md)
- [Agents guide](agents/README.md)
- [varde-code guide](clis/code/README.md)
- [varde-workflow guide](clis/workflow/README.md)
- [varde-toz guide](clis/toz/README.md)
- [varde-learn guide](clis/learn/README.md)
- [Repository contributor instructions](AGENTS.md)

## License

All modules share the [MIT License](LICENSE).

# varde

`varde` provides reusable workflow skills, installable subagents, and Rust CLI
crates in one workspace at `clis/Cargo.toml`. The `skills/` and `agents/`
folders remain self-contained. Run `just test` at the root for repository checks.

See [AGENTS.md](AGENTS.md) for the repository conventions used by contributors
and coding agents.

## Choose a module

| Module | Use it when | Main deliverable |
|---|---|---|
| [`skills/`](skills/README.md) | You want agent workflows for planning, building, reviewing, documenting, and related work. | `varde-*` skills for Claude, Codex, opencode, and Pi. |
| [`agents/`](agents/README.md) | You want ready-made plan, execution, review, and exploration subagents. | Harness-specific agent definitions for Claude, Codex, opencode, and Pi. |
| [`clis/code/`](clis/code/README.md) | You need local symbol extraction, code queries, structural search, or scans. | The `varde-code` module crate, exposed through `varde`. |
| [`clis/workflow/`](clis/workflow/README.md) | You need a generic markdown knowledge store. | The `varde-workflow` and `varde-workflow-core` crates, exposed through `varde`. |
| [`clis/toz/`](clis/toz/README.md) | You need to keep large tool output out of an agent's context window. | The `varde-toz` (tool-output-zone) module crate, exposed through `varde`. |
| [`clis/doc/`](clis/doc/README.md) | You need agent-doc lint, frontmatter, or flow checks. | The `varde-doc` module crate, exposed through `varde`. |
| [`clis/learn/`](clis/learn/README.md) | You need skill evaluations or the global friction store. | The `varde-learn` module crate, exposed through `varde`. |

The Rust crates share `clis/Cargo.toml`; their dependency rules are enforced by
`cd clis && cargo test -p varde --test dependency_rules`. Shared code belongs
in `varde-core` and `varde-contracts`. Skills invoke CLI functionality through
the installed `varde` binary. Friction recording uses `varde learn` and the
global store; report failures instead of writing a Markdown fallback.

## Quick start

Install the single `varde` CLI, then sync the skills and agents you want to use.
Each module README is the authoritative usage guide.

### Wire supported harnesses

Use the installed CLI to resolve saved targets and select harnesses:

```sh
varde setup sync --skills-dir <dir> --agents-dir <dir> --dry-run
varde setup sync --skills-dir <dir> --agents-dir <dir> --link-mode copy
```

The explicit target directories are saved in `<config>/varde/config.toml`.
Choose `--link-mode copy` to copy files into harness directories. Otherwise the
recommended arrangement is one canonical copy (for example,
`~/.agents/skills` and `~/.agents/agents`) symlinked into each harness.

To wire a selected harness, pass the canonical target directories and
`--harnesses`. Add one or more `--instructions-target <file>` values when you
want to install the shared instruction block:

```sh
varde setup sync --skills-dir <dir> --agents-dir <dir> --harnesses codex
```

### Install a preset

`varde setup sync --preset <name>` adds a preset's skills and their `requires`
closure to the selection; combine it with `--skills`:

```sh
varde setup sync --preset toz       # captured tool output
varde setup sync --preset docs      # documentation tools
varde setup sync --preset knowledge # durable project knowledge
varde setup sync --preset learn   # session diagnosis, friction, and skill evals
varde setup sync --preset scan    # code queries, scans, and scan-rule authoring
varde setup sync --preset workflow
varde setup sync --preset full
```

`workflow` includes planning, building, review, and documentation skills.
`full`, or sync with no saved selection, installs every skill. `--skills all`
also resets a saved selection.

Sync derives instruction sections and hook features from the selected skills
and their `requires` closure. An unknown preset errors and lists the valid names.

### Upgrade

`varde setup sync` uses the saved canonical targets; rerun it after setup
changes:

```sh
varde setup sync
```

For configured instruction targets and synced harnesses, `workflow`, `full`,
and default all-skills installs retain the orchestration instruction block. A
hand-picked skill list without `varde-change` drops that block and the inbox
hook on the next sync.

Use `varde doc spec inventory` to check domain specs against source paths.

Module READMEs remain authoritative for module-specific development. Installed
skill descriptions remain the authoritative routing surface.

Varde installs thirteen skills by default:

| Skill | Primary intent |
|---|---|
| `varde-explore` | Exploration and rich code explanation |
| `varde-change` | Planning, building, verification, and conclusion |
| `varde-review` | Review reports and explicit improvement modes |
| `varde-docs` | User documentation and generated specifications |
| `varde-knowledge` | Durable knowledge and session notes |
| `varde-learn` | Real friction capture, reconciliation, distillation, and skill evaluations |
| `varde-prototype` | Throwaway visual and logic prototypes |
| `varde-agent-doc-authoring` | Instructions and references for agents |
| `varde-code` | Indexed code queries for declarations and file relationships |
| `varde-manage` | Installation, configuration, and harness hooks |
| `varde-customize` | Scan-rule and output-profile authoring |
| `varde-toz` | Query and analyze captured tool output |
| `varde-scan` | Run rule scans and review code findings |

Natural language selects each skill and internal mode.
Ask for exploration before choosing implementation direction.
Request explanation when learning how a module works.
Use planning before uncertain or multi-part changes.
Use building after scope and acceptance criteria settle.
Request review for report-only findings across changed code.
Record knowledge when decisions must outlive one session.

### Index and scan a repository

Install the scan preset (code queries, scans, and rule authoring, plus the
always-installed `varde-manage`), build the repository index, and run a scan:

```sh
varde setup sync --preset scan
varde map build --repo-root .
varde scan --json '{"repoRoot":".","severityThreshold":"error"}'
```

Project knowledge lives in the root `memory-bank/knowledge/` bundle and is
reviewed and committed like source. Plans, reviews, and task evidence live in
the configured working store (`varde setup paths --json`). We recommend keeping
that store outside source repositories, under a shared root with distinct
project folders, preferably in a separate Git repository or storage with version
history. See the [recommended setup](skills/varde-manage/references/setup.md#recommended-working-memory-setup).
Personal knowledge remains outside this repository.

### Diagnose sessions and track friction

Install the learn skill on its own for session diagnosis, friction tracking,
and skill evaluations:

```sh
varde setup sync --skills varde-learn
```

`varde learn diagnose list` reads recent local sessions for a repository and
groups linked workers; `--run` returns a selected root session with its
workers. `varde learn friction` stores recurring issues in the global user
store, with optional repository filtering. `varde learn eval` measures skill
triggers and output quality. If you install the shared instruction block,
sync includes its optional learn guidance when `varde-learn` is selected.
See the [learn README](clis/learn/README.md) for commands and limits.

### Workflow skills

Install the single CLI and sync skills and agents into canonical directories:

```sh
cd clis && cargo install --path varde --locked --force --target-dir target
varde setup sync --skills-dir ~/.agents/skills --agents-dir ~/.agents/agents
```

Pass one or more `--instructions-target <file>` values to install the shared
instruction block. The skills cover the full workflow, including planning,
implementation, review, documentation, and session continuity. See the
[skills README](skills/README.md) for the full skill list and trigger guidance.

### Subagents

The sync command installs the available agents for detected harnesses. Pass
`--harnesses <ids>` to select harnesses explicitly. The available agents are
`varde-planner`, `varde-builder`, `varde-reviewer`, and `varde-explorer`; see
the [agents README](agents/README.md) for harness-specific details.

### Code intelligence

The `varde` CLI indexes a repository locally, then exposes symbol, dependency,
hotspot, mapping, pattern-search, and rule-scan queries. Build and test the
workspace from `clis/`:

```sh
cd clis
cargo build --workspace --locked
cargo test --workspace --locked
cargo install --path varde --locked --force --target-dir target
```

After installation, query a repository directly. Build remains optional:

```sh
varde map hotspots --json '{"repoRoot":"."}'
varde map build --repo-root .
```

See the [code CLI README](clis/code/README.md) for supported languages,
installation releases, query commands, and architecture documentation.

### Knowledge tools

The `workflow` workspace provides two components:

- `varde-workflow-core`, the library for concept and bundle operations.
- `varde-workflow`, the CLI for creating, reading, searching, updating, and
  linting markdown knowledge bundles.

The crates are part of the workspace at `clis/Cargo.toml`. Use `varde plan`
for workflow commands.

`workflow` is pre-alpha. Its detailed [README](clis/workflow/README.md) documents
the workflow, command syntax, and knowledge-bundle layout.

## Development workflow

Work within the module you change. Run commands from that folder, use its
local instructions, and keep changes inside that module unless a coordinated
repository-level documentation update is needed.

| Module | Build | Test | Install |
|---|---|---|---|
| `skills/` | Not applicable | `./check-refs.sh && for test_file in tests/*.sh; do "$test_file"; done` | `varde setup sync` |
| `agents/` | `./generate.py --check` | `./test-consolidated-skills.sh` | `varde setup sync` |
| `clis/` | `cargo build --workspace --locked` | `cargo test --workspace --locked` | `cargo install --path varde --locked --force --target-dir target` |

Skills and agents are installed with `varde setup sync`. Run Rust workspace
commands from `clis/`; module `AGENTS.md` or `CLAUDE.md` files may add local
rules.

## Repository layout

```text
varde/
├── skills/          Reusable varde-* agent workflow skills
├── agents/          Installable harness-specific subagent definitions
└── clis/            One Cargo workspace (`clis/Cargo.toml`)
    ├── code/        varde-code
    ├── workflow/    varde-workflow-core and varde-workflow
    ├── toz/         varde-toz (tool-output-zone)
    ├── doc/         varde-doc
    └── learn/       varde-learn
```

## Documentation

Use the module documentation for implementation details:

- [Skills guide](skills/README.md)
- [Agents guide](agents/README.md)
- [Code module guide](clis/code/README.md)
- [Workflow module guide](clis/workflow/README.md)
- [Toz module guide](clis/toz/README.md)
- [Doc module guide](clis/doc/README.md)
- [Learn module guide](clis/learn/README.md)
- [Repository contributor instructions](AGENTS.md)

## License

All modules share the [MIT License](LICENSE).

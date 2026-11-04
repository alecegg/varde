# Varde

Varde is a command-line toolkit for working with coding agents. It builds code maps and scans, captures noisy command output, tracks plans and reviews, and records what agents learn. It ships skills and agents for Claude, Codex, OpenCode and Pi.

This repository is a Python workspace of twelve modules. See [AGENTS.md](AGENTS.md) for the module table, layer rules and checks, and [CHANGELOG.md](CHANGELOG.md) for release notes.

## Install from a release

Python 3.14 or newer must be on your `PATH`.

1. Download `varde.pex` from the [latest release](https://github.com/alecegg/varde/releases/latest).
2. Make it executable and check the version:

```sh
chmod +x varde.pex
./varde.pex --version
```

This prints `varde 1.0.0`. Put the file on your `PATH` as `varde` to use it everywhere. The PEX does not include `varde-serve`; install from a checkout to get it.

## Install from a checkout

The project pins Python 3.14.7 (`.python-version`) and uv 0.12.19 (`pyproject.toml`). Run this from the main checkout, not a linked worktree:

```sh
python3 runner/deploy/deploy.py
```

It installs the CLI and `varde-serve`, swaps them in atomically, and restarts the runner. Do not run `uv tool install --force` on a live install, because `varde` is missing while it runs. See [runner/deploy/README.md](runner/deploy/README.md).

## First commands

```sh
varde --version          # varde 1.0.0
varde setup sync --dry-run   # preview the skills and agents it would install
varde setup sync         # install them for the detected harnesses
varde --help             # list command groups
```

Main command groups:

- `map`, `scan`, `edit`: code index, rule scans, AST edits.
- `plan`, `run`, `msg`: plans and reviews, output capture, agent messages.
- `learn`, `design`, `setup`: learning loop, design checks, install.
- `runner`, `serve`: runner switch, local daemon.

Run `varde <group> --help` for each.

## Modules

| Module | Purpose |
| --- | --- |
| `core`, `data` | Shared files, storage contracts, config and locking |
| `toz`, `code` | Command-output capture; code index, scans and edits |
| `learn` | Sessions, friction, knowledge and docs upkeep |
| `workflow` | Plans, builds, reviews and orchestration |
| `design`, `visualize`, `dev` | Design checks, charts and pages, prototyping |
| `app`, `runner`, `serve` | The `varde` CLI, the agent runner, the local daemon and API |

## Development

Run commands from the repository root.

```sh
just test-fast           # non-slow tests for every module
just test-changed        # changed modules and the modules above them
just test-baseline       # every test, including slow ones
VARDE_TEST_JOBS=1 just test-baseline   # reliable full run
```

Use `VARDE_TEST_JOBS=1` for a full run, because concurrent modules make the Chromium page tests flaky.

- `uv run pytest <module>/tests` runs one module.
- `just hooks` installs the git hooks.
- [AGENTS.md](AGENTS.md) lists every check.

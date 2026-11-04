# Varde

Varde is a command-line toolkit for working with coding agents. It builds code maps and scans, captures noisy command output, tracks plans and reviews, and records what agents learn. It ships skills and agents for Claude, Codex, OpenCode and Pi.

This repository is a Python workspace of twelve modules. See [AGENTS.md](AGENTS.md) for the module table, layer rules and checks, and [CHANGELOG.md](CHANGELOG.md) for release notes.

## Install from a release

- Built for: macOS arm64 (wheels are `macosx_11_0_arm64`).
- Needs: CPython 3.14 or newer on your `PATH`.
- Other platforms: build your own with `uv run --locked python app/pex/build.py <dir>`.

1. Download `varde.pex` from the [latest release](https://github.com/alecegg/varde/releases/latest).
2. Make it executable and put it on your `PATH` as `varde`:

   ```sh
   chmod +x varde.pex
   mv varde.pex ~/.local/bin/varde
   ```

3. Check the version; it prints `varde 1.0.0`:

   ```sh
   varde --version
   ```

The PEX does not include `varde-serve`; install from a checkout to get it.

## Install from a checkout

Requires uv 0.12.19 (pinned in `pyproject.toml`); the project pins Python 3.14.7 (`.python-version`). Run this from the main checkout, not a linked worktree:

```sh
python3 runner/deploy/deploy.py
```

It installs the CLI and `varde-serve`, swaps them in atomically, and restarts the runner (`--skip-runner` skips the restart). Do not run `uv tool install --force` on a live install, because `varde` is missing while it runs. See [runner/deploy/README.md](runner/deploy/README.md).

## First commands

```sh
varde --version              # varde 1.0.0
varde setup sync --dry-run   # preview what it would install
varde setup sync             # install for the detected harnesses
```

`varde setup sync`:

- Links skills and agents into each detected harness's directories (default link mode: symlink).
- In a git main checkout, also adds a managed pointer block to `AGENTS.md` and builds repo-map packs (`--no-packs` skips the packs).

See `varde --help` for the command groups and [AGENTS.md](AGENTS.md) for the module table and layer rules.

## Development

Run commands from the repository root.

```sh
just test-fast           # non-slow tests for every module
just test-changed        # changed modules and the modules above them
just test-baseline       # every test, including slow ones
```

`VARDE_TEST_JOBS=1 just test-baseline` runs the modules in sequence.

- `uv run pytest <module>/tests` runs one module.
- `just hooks` installs the git hooks.
- [AGENTS.md](AGENTS.md) lists every check.

## License

MIT. See [LICENSE](LICENSE).

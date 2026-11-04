# varde-py

Python implementation of the Varde CLI, its skills, and workflow agents. The
workspace is organized into ten capability modules, each with its own uv
project, package, and tests. Skills ship once as package data and are discovered
through package entry points.

The project pins Python 3.14.7 in `.python-version` and uv 0.12.19 in
`pyproject.toml`. Use `dev/scripts/with-lock.sh` around environment setup and
other heavy or measured commands. See `dev/scripts/` for SSD write measurement tools.

## Development

Run tests one package at a time to avoid pytest import collisions between
same-named test modules:

```sh
uv run pytest core/tests
uv run pytest toz/tests
uv run pytest code/tests
uv run pytest learn/tests/loop
uv run pytest learn/tests/docs
uv run pytest learn/tests/knowledge
uv run pytest workflow/tests
bash dev/tests/prototype-verifier.sh
uv run pytest dev/scripts/test_quiet_check.py
uv run pytest app/tests
just test
```

Install the CLI from this checkout and sync skills and agents with the
commands below on a fresh machine. To update an existing install, run
`python3 runner/deploy/deploy.py` instead:

```sh
uv tool install --force --from ./app varde
varde --version
varde setup sync
```

Check the approved worktree window with `python dev/scripts/check_window.py`; see
[`dev/scripts/window-agreements.md`](dev/scripts/window-agreements.md) for the
agreements.

See [AGENTS.md](AGENTS.md) for the module map, package boundaries, and checks.

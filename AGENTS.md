# varde-py

Python workspace for the Varde CLI, skills, and harness agents. Run commands
from the repository root unless a package command says otherwise.

## Repository layout

Read `docs/repo-map/README.md` first (optional when the task names one module),
then the module pack for the folder you edit. After merging to main, run `just repo-map-refresh`.

The root workspace contains twelve capability modules. Each module is a uv
project with its package in `src/`, tests in `tests/`, and any module scripts or
documentation beside them. Skills are package data under
`<module>/src/<pkg>/skills`; `<module>/skills` is a discovery symlink. Workflow
agents live in `workflow/src/varde_workflow/agents/`.

| Module | Distribution | Level | Skills | Install preset |
| --- | --- | ---: | --- | --- |
| `core` | `varde-core` | 0 | shared files | `core` |
| `toz` | `varde-toz` | 1 | `varde-toz` | `toz` |
| `code` | `varde-code` | 1 | `varde-code`, `varde-scan`, `varde-customize` | `code` |
| `learn` | `varde-learn` | 2 | `varde-learn`, `varde-diagnose`, `varde-improve`, `varde-knowledge`, `varde-session-notes`, `varde-docs`, `varde-skill-authoring`, `varde-doc-authoring` | `learn` |
| `workflow` | `varde-workflow` | 3 | `varde-plan`, `varde-build`, `varde-orchestrate`, `varde-swarm`, `varde-review`, `varde-review-ui`, `varde-verify` | `workflow` |
| `design` | `varde-design` | 1 | `varde-design` | `design` |
| `visualize` | `varde-visualize` | 1 | `varde-visualize` | `visualize` |
| `dev` | `varde-dev` | 1 | `varde-prototype`, `varde-explore`, `varde-explain`, `varde-pr` | `dev` |
| `app` | `varde` | 4 | `varde-manage` | `app` |
| `runner` | `varde-runner` | 4 | — | — |
| `serve` (daemon, local API, MCP stdio shim) | `varde-serve` | 4 | — | — |
| `data` (shared storage contracts, config, locking, versioning, lazy domain opening) | `varde-data` | 1 | — | — |

`learn` has three subpackages (`loop`, `docs`, `knowledge`) with tests in
`learn/tests/loop`, `learn/tests/docs` and `learn/tests/knowledge`; see
`learn/AGENTS.md`. `memory_dirs.py` stays in `core`.

Benchmark harnesses and corpora live in `code/bench` and `runner/bench`; run them with `uv run python` / `uv run pytest`.

`layers.toml` is the source of truth for module levels and declared file
couplings. Modules may depend on and import only strictly lower levels;
`core/tests/test_dependency_rules.py` and `core/tests/test_layer_couplings.py`
enforce those rules. `just test-changed` tests the changed module plus modules
above it through reverse dependencies and declared couplings, plus the layer
dependency test. Paths outside a workspace module, plus changes to `core` or
`layers.toml`, select all test-fast modules. Use
`just test-baseline` for merge-ready, large cross-cutting changes, or changes
to `layers.toml` or `core`. Skills call the installed `varde` command rather
than importing package source.

Skills are slim and carry no per-topic pointers. Per-skill how topics (steps,
methods, examples) are listed with `varde learn how <skill>` and read with
`varde learn how <skill> <step>`.

## CLI updates

After changing a CLI package, run its package checks and relevant workspace
checks. Install this checkout with `python3 runner/deploy/deploy.py` (atomic
CLI swap, runner restart; see `runner/deploy/README.md`), then verify
`varde --version` and any changed command. The same run installs `varde-serve`
(`~/.local/bin/varde-serve`) as a second atomic tool swap; `varde serve` needs
it, and the PEX excludes it (`--skip-serve` skips it). Run it from the main checkout: a
hook blocks `uv tool install` in linked worktrees. Never run
`uv tool install --force` on the live install: `varde` is missing while it
runs. For a portable CLI PEX build,
run `uv run --locked python app/pex/build.py <temp-dir>` and verify
`<temp-dir>/varde.pex --version`.

## Checks

- [Sandbox permissions for running the app and tests](docs/sandbox-permissions.md).
- When a change adds or needs a sandbox or harness permission, update `docs/sandbox-permissions.md` in the same change.
- After editing a skill or how topic, run `varde learn check <path>` and clear its `sentence` warnings (sentences above 25 words; see the `sentence-style` reference). The check only warns and CI does not run it.
- `uv run pytest <module>/tests` runs a module's tests from the repository root.
- `just test-fast` runs every module's non-slow pytest tier; pass module names
  to limit it, or use `just test-changed` for changed modules and dependents.
  Both use xdist with 2 workers for core, code, workflow, and data.
- Mark slow pytest cases with `@pytest.mark.slow`; run them with
  `uv run pytest <module>/tests -m slow`. `just test` runs every Python test,
  including slow cases. `just test-all` also runs the slow shell-test tier.
- Run `just test-prep` after Python dependency or runner UI source changes.
- `./core/scripts/check-refs.sh` validates skill references.
- `uv run pytest app/tests/test_installed_wheels.py -q` verifies skills ship in
  module wheels and sync installs the expected sets.
- `uv run python app/scripts/generate.py --check` validates generated agent files.
- `bash dev/tests/prototype-verifier.sh` and
  `uv run pytest dev/tests/test_quiet_check.py` run developer tests.
- `just test` runs all module tests and the fast shell tier, then skill and agent
  checks. `just test-all` also runs the slow shell tier (the CI command).
- Use `just test-baseline` for branch comparisons; it runs every module test, including slow tests, under `core/scripts/test-env.sh`.
- `just test-baseline` runs at most two modules concurrently by default (about one per four CPUs). Set positive `VARDE_TEST_JOBS` to change module concurrency; 1 runs modules in sequence. Core, code, workflow, and data still use `-n 2`.
- UI and Unix-socket skips are reported; backend-capability and opt-in `VARDE_*` skips are expected. Browser, Playwright, and WebKit skips fail.
- `core/scripts/shell-test-tiers.txt` gives every shell test a tier (fast when
  its lowest observed run was under 20 s) and its measured seconds; the runner
  fails when a test has no line there or when the list is missing.
- `just test-licenses` checks dependency licenses.

## Git hooks

- Run `just hooks` or `.githooks/install` to install the tracked hooks. This sets
  the repo-local `core.hooksPath`.
- Configure `.githooks/pyright-stage` with `pre-commit`, `pre-merge-commit`, or
  `pre-push`; the default is `pre-merge-commit pre-push`.
- Fast-forward merges run the post-merge guard. Squash and non-fast-forward
  merges skip it; pre-merge-commit already checks those merge commits.
- The post-merge hook reports pyright failures but cannot abort a merge. A
  conflicted merge finished with `git commit` runs pre-commit; pre-push covers it.
- `--no-verify` skips hooks. Hooks are inactive in agent-memory. Ruff checks
  working-tree files, including unstaged edits.

<!-- varde-map:start -->
Read `docs/repo-map/README.md` first, then the module pack for the folder you edit.
Check freshness with `varde map packs status --check`; refresh with `varde map packs build --stale`.
<!-- varde-map:end -->

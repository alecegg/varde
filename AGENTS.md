# AGENTS.md — varde monorepo

This repo combines four previously separate projects into one working tree. It is a **monorepo with convention-based module boundaries**, not a unified build.

## Module convention

The `skills/` and `agents/` folders and each workspace under `clis/` are self-contained modules:

- `skills/` — the `varde-*` skills (markdown + shell tooling).
- `agents/` — installable subagent definitions, one variant per harness (markdown + shell tooling).
- `clis/code/` — the `varde-code` Rust CLI (its own Cargo workspace).
- `clis/workflow/` — the `varde-workflow` CLI and `varde-workflow-core` library (its own Cargo workspace).
- `clis/toz/` — the `varde-toz` (tool-output-zone) Rust CLI (its own Cargo workspace).
- `clis/learn/` — the `varde-learn` Rust CLI for skill trigger/output evals and global friction storage (its own Cargo workspace).

Rules that keep the modules independent:

1. **No cross-folder source or dependency imports.** `clis/code/`, `clis/workflow/`, `clis/toz/`, and `clis/learn/` are separate Cargo workspaces and must stay that way — do not add a root or `clis/Cargo.toml`, and do not add path dependencies from one folder into another. The skills reach the CLIs only through the installed binaries on `PATH`, never by relative path into a sibling folder.
   - Each skill under `skills/` owns its own flat `references/` directory and is self-contained; `install.sh` copies one skill directory at a time. Guidance a skill needs is written into that skill, never imported from a sibling folder. Exception: files listed in `skills/shared/MANIFEST` have one source under `skills/shared/`, and `install.sh` copies them into every skill the manifest names, so an installed skill still stands alone.
   - `skills/check-refs.sh` guards this: it installs into a temp dir and fails on any pointer that would not resolve on a user's machine.
2. **Build and test within a folder.** `cd clis/code && cargo test`, `cd clis/workflow && cargo test`, `cd clis/toz && cargo test`, `cd clis/learn && cargo test`, `cd skills && ./install.sh`, `cd agents && ./install.sh`. There is no root build or test entry point. `varde sync` is the only root wiring entry point. It only wires supported harnesses through module installers.
3. **Names keep the `varde-` prefix.** Folders are short (`clis/code/`, `clis/workflow/`, `skills/`, `agents/`, `clis/toz/`), but package names, CLI names, and skill names retain their full `varde-*` identity where applicable (`varde-toz` also installs `toz` as a compatibility alias). Plugin identities use the same prefix; module-specific environment variables use `VARDE_<MODULE>_*`. Legacy names may remain as compatibility inputs, with canonical names taking precedence.
4. **Each folder owns its own docs.** Per-folder `README.md` and `AGENTS.md`/`CLAUDE.md` govern work inside that folder. The root `memory-bank/knowledge/` is the sole committed knowledge bundle. When working in a folder, follow its local instructions.
5. **Knowledge is durable.** Commit `memory-bank/knowledge/` content. Keep
   the configured working store for plans and reviews local. Friction belongs
   to the user's global `varde-learn` SQLite store; keep the live database
   outside Git. Review Markdown exports for private evidence before sharing or
   committing them. Personal knowledge belongs outside this repository.
   Working and knowledge paths can be redirected per user with
   `varde-workflow paths set`; the setting lives in
   `~/.config/varde/config.toml`, never in the repo.

## CLI updates after a plan

For each GitHub release, all four CLI package `version` fields must match the
release tag, without its leading `v` in Cargo (for example, tag `v1.4.0` uses
package version `1.4.0`).

After a plan changes any CLI module, run its required checks, then rebuild and
install every affected binary from this checkout before reporting completion.
Run the matching command inside the module directory:

| Module | Install command |
|---|---|
| `clis/code/` | `cargo install --path crates/varde-code --locked --force --target-dir target` |
| `clis/workflow/` | `cargo install --path varde-workflow --locked --force --target-dir target` |
| `clis/toz/` | `cargo install --path crates/toz --locked --force --target-dir target` |
| `clis/learn/` | `cargo install --path crates/varde-learn --locked --force --target-dir target` |

Verify that `command -v <binary>` selects the installed executable, run its
`--help`, and check any CLI flags changed by the plan. Use `--force` even when
the package version is unchanged. If installation or verification fails,
report the failure and the remaining update before claiming completion.
A change to review fingerprint inputs makes in-flight approvals stale, so re-record them after installing.

## Sandbox and shell

An optional tool that keeps state outside the workspace — an index, a lock, a
cache, a personal store — will be denied by the sandbox before it fails on its
own terms. The posture is the same for all of them: retry the call once with
escalated access, unchanged; if that is denied or fails, use the plain Read/Grep
path and say which capability was lost. Degrading is fine; degrading silently is
what costs the next session.

The uv and zsh gotchas below remain in legacy `working/friction` Markdown.
Their fixes stay here; new friction is recorded through the global
`varde-learn` store.

**`uv` cannot reach its managed Python.** `uv run` tries to read
`~/.local/share/uv/python` and fails with `Operation not permitted`, which stops
`skills/varde-agent-doc-authoring/scripts/validate-frontmatter.py`. The fix is
to use the interpreter already on `PATH` rather than escalating:

```bash
UV_PYTHON_PREFERENCE=only-system uv run scripts/validate-frontmatter.py <skill-dir>
```

`UV_CACHE_DIR` does not help — the cache is not what is blocked.

**`path` is a reserved array in zsh.** Assigning it in a loop (`for path in ...`)
rewrites `$PATH`, and every later command in that shell resolves to nothing. Name
the variable for what it holds — `skill_dir`, `target` — in any shell snippet
this repo's tooling runs.

## Provenance

These folders were imported fresh (no combined git history). The original per-project history remains in the standalone repositories they came from.

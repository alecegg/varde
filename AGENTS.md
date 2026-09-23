# AGENTS.md — varde monorepo

This repo combines three previously separate projects into one working tree. It is a **monorepo with convention-based module boundaries**, not a unified build.

## Module convention

Each top-level folder is a self-contained module:

- `skills/` — the `varde-*` skills (markdown + shell tooling).
- `agents/` — installable subagent definitions, one variant per harness (markdown + shell tooling).
- `code-cli/` — the `varde-code` Rust CLI (its own Cargo workspace).
- `workflow-cli/` — the `varde-workflow` / `okf-core` / `docwatch` Rust CLIs (its own Cargo workspace).

Rules that keep the modules independent:

1. **No cross-folder source or dependency imports.** `code-cli/` and `workflow-cli/` are separate Cargo workspaces and must stay that way — do not add a root `Cargo.toml`, and do not add path dependencies from one folder into another. The skills reach the CLIs only through the installed binaries on `PATH`, never by relative path into a sibling folder.
   - Each skill under `skills/` owns its own flat `references/` directory and is self-contained; `install.sh` copies one skill directory at a time. Guidance a skill needs is written into that skill, never imported from a sibling folder.
   - `skills/check-refs.sh` guards this: it installs into a temp dir and fails on any pointer that would not resolve on a user's machine.
2. **Build and test within a folder.** `cd code-cli && cargo test`, `cd workflow-cli && cargo test`, `cd skills && ./install.sh`, `cd agents && ./install.sh`. There is no root build or test entry point. `varde init` is the only root wiring entry point. It only wires supported harnesses through module installers.
3. **Names keep the `varde-` prefix.** Folders are short (`code-cli/`, `workflow-cli/`, `skills/`, `agents/`), but package names, CLI names, and skill names retain their full `varde-*` identity.
4. **Each folder owns its own docs.** Per-folder `README.md`, `AGENTS.md`/`CLAUDE.md`, and `memory-bank/` govern work inside that folder. When working in a folder, follow its local instructions.
5. **Knowledge is durable.** Commit `memory-bank/knowledge/` content. Keep
   `memory-bank/working/` (including `working/friction/`) local. Personal
   knowledge belongs outside this repository. Either directory can be
   redirected per user with `varde-workflow paths set`; the setting lives in
   `~/.config/varde/paths.toml`, never in the repo.

## Sandbox and shell

An optional tool that keeps state outside the workspace — an index, a lock, a
cache, a personal store — will be denied by the sandbox before it fails on its
own terms. The posture is the same for all of them: retry the call once with
escalated access, unchanged; if that is denied or fails, use the plain Read/Grep
path and say which capability was lost. Degrading is fine; degrading silently is
what costs the next session.

Two environment gotchas bite repeatedly when working here under a sandbox; both
are recorded in `memory-bank/working/friction/`.

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

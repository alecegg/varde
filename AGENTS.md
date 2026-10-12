# AGENTS.md — varde monorepo

This repository contains reusable skills, agents, and Rust CLI crates in one workspace at `clis/Cargo.toml`.

## Module convention

The `skills/` and `agents/` folders are self-contained modules. The `clis/` folders group crates in that workspace:

- `skills/` — the `varde-*` skills (markdown + shell tooling).
- `agents/` — installable subagent definitions, one variant per harness (markdown + shell tooling).
- `clis/code/` — the `varde-code` module crate.
- `clis/workflow/` — the `varde-workflow` and `varde-workflow-core` module crates.
- `clis/toz/` — the `varde-toz` (tool-output-zone) and `varde-toz-core` module crates.
- `clis/doc/` — the `varde-doc` module crate for agent-doc lint, frontmatter, and flow checks.
- `clis/learn/` — the `varde-learn` and `varde-learn-core` module crates for skill evaluations and friction storage.
- `clis/varde-core/` and `clis/varde-contracts/` — shared crates used by the module crates.
- `clis/varde/` — the application crate and installed `varde` CLI.

Rules that keep the modules independent:

1. **Keep shared code and dependencies within the workspace rules.** Check `cd clis && cargo test -p varde --test dependency_rules`: `varde-core` has no `varde-*` dependency, `varde-contracts` depends only on it, module crates may depend on those shared crates and their own family’s `-core` crate when present, and only app `varde` depends on module crates. Skills call the installed `varde` binary, never sibling builds; do not import source or add path dependencies across module families.
   - Skills own flat `references/` folders. The CLI embeds shared guidance from `skills/shared/` in its skill bundle. `skills/check-refs.sh` checks installed pointers.
2. **Build, test, install, and sync through the owning entry points.** Run `cd clis && cargo test --workspace --locked`, `cd skills && ./check-refs.sh`, and `cd agents && ./generate.py --check`; run `just test` at the root for all repository checks. Install with `cd clis && cargo install --path varde --locked --force --target-dir target`. Use `varde setup sync` to wire supported harnesses.
3. **Keep canonical names:** use `varde-` for package, skill, and plugin identities, and run commands through `varde`. The legacy binary names (`toz`, `varde-toz`, `varde-code`, `varde-workflow`, `varde-learn`) are retired; `tests/old-binary-names.sh` enforces this. Name module variables `VARDE_<MODULE>_*`, with canonical names taking precedence.
4. **Follow local docs and keep knowledge durable.** Folder-level `README.md`, `AGENTS.md`, and `CLAUDE.md` files govern their modules. Commit `memory-bank/knowledge/`; keep plans and reviews in the configured work store. The friction log may live in a private Git repo so it can be shared and merged; its SQLite cache stays git-ignored. Review Markdown exports for private evidence and keep personal knowledge outside the repository. Use `varde setup paths set` to redirect stores; settings live in `~/.config/varde/config.toml`.

## CLI updates after a plan

For each GitHub release, the workspace package version in `clis/Cargo.toml`
must match the release tag without its leading `v` (for example, tag `v1.4.0`
uses package version `1.4.0`).

After a plan changes a CLI module, run its required checks, then rebuild and
install this checkout's single `varde` binary:

```bash
cargo install --path varde --locked --force --target-dir target
```

Install only after the plan has merged, from the checkout that merged it; before then, put `clis/target/debug` first on `PATH` because `cargo install` replaces the binary other sessions call.

Verify that `command -v varde` selects this binary, run `varde --help`, and check
any CLI flags changed by the plan before reporting completion. Use `--force`
even when the package version is unchanged. If installation or verification
fails, report the failure and the remaining update.
A change to review fingerprint inputs makes in-flight approvals stale, so re-record them after installing.

## Sandbox and shell

An optional tool that keeps state outside the workspace — an index, a lock, a
cache, a personal store — will be denied by the sandbox before it fails on its
own terms. The posture is the same for all of them: retry the call once with
escalated access, unchanged; if that is denied or fails, use the plain Read/Grep
path and say which capability was lost. Degrading is fine; degrading silently is
what costs the next session.

The zsh gotcha below remains in legacy `working/friction` Markdown.
Its fix stays here; new friction is recorded through the global
`varde-learn` store.

**`path` is a reserved array in zsh.** Assigning it in a loop (`for path in ...`)
rewrites `$PATH`, and every later command in that shell resolves to nothing. Name
the variable for what it holds — `skill_dir`, `target` — in any shell snippet
this repo's tooling runs.

## Provenance

These folders were imported fresh (no combined git history). The original per-project history remains in the standalone repositories they came from.

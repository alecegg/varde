# Flow walkthrough, pass 4: varde skills and CLI integration (2026-09-25)

## How to read this

Items are ordered by priority, highest first. Each item names its evidence:

- **Repro**: reproduced in a temp repo or against the live CLI.
- **Checked**: confirmed in source, but not reproduced.
- **Inferred**: reasoned from the instruction text. Plausible, but no agent run confirmed it.

Baseline (all pass): `check-refs.sh`, all `skills/tests` and `agents/tests`,
`validate-frontmatter.py` on all 7 skills, and `generate.py --check`. Every
cited `varde-workflow` and `varde-code` subcommand, flag, and JSON field exists.
A fresh `varde sync` into a temp `$HOME` (claude, codex, opencode) is clean and
idempotent.

The two highest-priority items share one root cause. `<working>` resolves from
the cwd's project root, and a checked-in `memory-bank/` pins that root to the
current checkout. See P1 and P2.

## P1: Critical, breaks work or leaks data

### 1. Linked worktrees resolve `<working>` to an empty in-worktree directory. Repro.
- Where: `md-core/src/memory.rs` `find_root` (the `memory_bank_ancestor` check runs before the config and git-common-dir checks). The skills' Gotchas tell agents to resolve `<working>` with `varde-workflow paths --json`.
- Repro: `git worktree add $TMPDIR/wtprobe` and then `varde-workflow paths --json` inside it returns `root=<worktree>`, `working=<worktree>/memory-bank/working`, and `working_source=builtin`. The main checkout returns the configured vault working store (`project`).
- Failure: the committed `memory-bank/knowledge/` makes every worktree look like its own project root. So the config's project entry and the git-common-dir fallback never run. An executor in a parallel, refactor, or build worktree gets a `<working>` with no plans, tasks, or handoffs. A plan, status, or handoff call made from a worktree reads or writes the wrong store. The `varde-worktrees/...` entry in `paths.toml` looks like a manual workaround for this.
- Fix: in `find_root`, map a linked worktree to its main checkout (git-common-dir) before accepting a `memory-bank/` ancestor. Alternatively, have `paths` check the config's project keys against the main-worktree root.

### 2. `conclude` writes absolute personal paths into committed knowledge. Checked.
- Where: `memory-bank/knowledge/conclusions/2026-09-24-workflow-cli-cleanup.md:11` and `2026-09-25-skills-agents-installers-fixes.md:11` contain `plan: <absolute-vault-working-path>/...`. Older conclusions use `memory-bank/working/...`, which is gitignored.
- Failure: once working storage is redirected, committed notes leak a local path and personal folder names. In both cases the link can't resolve for anyone else, because working is local by design.
- Fix: have `conclude` record the plan id (folder name) instead of a path. Also scrub the two existing notes.

### 3. Plan Finalize tells the `plan` subagent to spawn a subagent it cannot spawn. Checked.
- Where: `varde-change/references/plan-fundamentals.md:30-31` says "Delegate one fresh-eyes review to a single subagent". `agents/plan/claude.md:33` and `opencode.md:38` say "Run Finalize's fresh-eyes review in-agent, never via a spawned agent". The `plan` agent has no Agent tool.
- Failure: every plan run through the `plan` agent hits contradictory instructions at Finalize. Commit `46a9052` updated the agent but not the reference.
- Fix: in `plan-fundamentals.md`, say "run the review yourself, or delegate it when you have an agent tool and are the top-level session".

## P2: High, wrong routing, dead ends, likely misfollowed

### 4. Parallel wave: with default storage (in-repo, gitignored), no step applies the task transitions. Checked.
- Where: `varde-change/references/build-parallel.md:30-40`. Step 6 covers "task files tracked in the repository". Step 7 covers "plan storage outside the repository" with "update external plan storage if needed". The root `.gitignore` ignores `**/memory-bank/working/`, so the default case matches neither step.
- Failure: workers are told not to write task files (`build-execution.md:64`). The orchestrator has no explicit step for the default layout, so tasks can stay `in_progress` after a successful wave. The next `readiness` or `next_wave` call then sees stale state.
- Fix: rewrite steps 6-7 by one rule: tracked files are updated in the integration worktree; for everything else (untracked or external), apply transitions after the fast-forward.

### 5. The `<working>` store depends on cwd in this monorepo. Repro.
- Where: `code-cli/` and `workflow-cli/` each have their own `memory-bank/`. `paths --json` run from `code-cli/` gives `.../varde/code-cli/working`. From the repo root or `skills/` it gives `.../varde/working`. The `skills/` project entry in `paths.toml` is dead because the root `memory-bank/` shadows it.
- Failure: an agent that `cd`s into a module between writing and resuming a plan or handoff sees a different store. For example, `varde-knowledge` handoff resume and `varde-change` status then report "nothing in flight". The skills say "resolve once before first use", but never from which directory.
- Fix: in the Gotchas, add "resolve from the directory whose `memory-bank/` owns the work, and reuse that result". Have `paths set` warn when a project key is shadowed by an ancestor `memory-bank/`.

### 6. `fix-pass` backups are flat copies, so a restore can corrupt files. Inferred.
- Where: `varde-review/references/fix-pass.md:17-19` says "copy each file it will touch to `$TMPDIR`". `simplify.md:30-32` has the same snapshot and restore steps.
- Failure: two touched files with the same basename (for example `a/index.ts` and `b/index.ts`) overwrite each other's backup. After a failed verification, one file is restored with the other's contents. Files the fix *creates* are never removed on restore.
- Fix: back up with relative paths preserved (`$TMPDIR/<run>/<repo-relative path>`), and delete created files on restore. A `git diff` patch that you reverse-apply is simpler still.

### 7. Blocked executors are told to edit `status` directly, even in parallel waves. Checked.
- Where: `varde-change/references/build-execution.md:58-61`: "Blocked: set `status: blocked`". This contradicts `varde-workflow-cli.md:24` ("change state through `transition`, never by editing `status`"). It also contradicts line 64, which says parallel workers do not write the task file.
- Failure: a blocked parallel worker writes a task file it doesn't own, and a serial worker skips the CLI's legal-move check.
- Fix: "Blocked: move the task to `blocked` with `varde-workflow transition` (serial or inline), or report `blocked` without touching the task file (parallel)."

## P3: Medium, inconsistencies or gaps with workarounds

### 8. `worktree.md` does not document merge exit 4. Checked.
- Where: `varde-change/references/worktree.md:19-20` lists exits 2, 3, and 5. `scripts/worktree-merge.sh:46,54,55,73` also exits 4 (missing branch, unresolved target, wrong checked-out branch, or a non-conflict merge failure).
- Fix: add "4 = target rejected; check the branch and target names, and never recreate a missing worker branch".

### 9. No skill owns CHANGELOG or release-note updates. Checked.
- Where: `varde-docs/SKILL.md:12` excludes them explicitly, and no other skill claims them.
- Fix: add a CHANGELOG row to `varde-docs`, or name the owner in the exclusion text.

### 10. Knowledge types don't match between the skill, `reflect`, and `note`. Checked.
- Where: the `varde-knowledge` description says "decision, pattern, definition, or obstacle". `reflect.md` step 2 says "decision, fact, pattern, or definition". `note.md` lists the types `definition`, `decision`, `pattern`, `reference`, and `spec`.
- Failure: "fact" has no folder. An agent might invent `fact/`, or guess `reference/`.
- Fix: map "fact" to `reference` in `note.md`, or use the same term list everywhere.

### 11. Every generated conclusion fails lint as orphaned. Repro.
- Where: `varde-workflow lint --bundle memory-bank/knowledge` returns 37 `orphaned_concept` warnings, mostly `conclusions/` and `promotions/`, which `conclude` writes and nothing links to.
- Failure: `varde-docs spec` step 6 reports lint findings, so every spec run surfaces noise the user can't act on, and real orphans get lost in it.
- Fix: have lint exempt producer-owned folders (`conclusions/`, `promotions/`), or have `conclude` add each new conclusion to an index.

### 12. Conclusion filenames use two conventions. Checked.
- Where: `conclusions/2026-09-24-workflow-cli-cleanup.md` and `conclusions/parallel-build-waves.md` sit in the same folder.
- Fix: pick one (dated matches plan ids) and rename the rest with `git mv`.

## P4: Low, wording and polish

13. `varde-prototype/SKILL.md:30` says "the track references call it `<storage>`", but only `logic-track.md` uses that name. `visual-track.md` names files with no directory. Fix: prefix `visual-track.md` paths with `<storage>/`. Checked.
14. `simplify.md`, `scan.md`, and `scan-author.md` lack the closing "record lessons with `varde-knowledge`" step that every other top-level flow has. Checked.
15. `varde-review/references/report.md:22-24` says "nearest merge or tag" but gives no command, while every other scope branch in that step does. Fix: name one, for example `git describe --tags --abbrev=0 || git merge-base HEAD origin/main`. Checked.
16. `skills/install.sh:272` prints "Done. Installed to: ..." before a later per-skill failure shows up in `varde sync`'s output (exit code is still correct). Reproduced only under a sandbox denial of `~/.agents`. Inferred relevance.
17. The `code-cli` `exact_clone_gates` tests are flaky under parallel `cargo test` because they share an SQLite path (`database is locked`). They pass with `--test-threads=1`. Fix: use a unique tempdir per test. Repro.

## Verified fixed from earlier passes

- F1: `resolve-execution-wave.py` parses unindented list items (reproduced; cycles exit 3).
- F2/D1: parallel task-file ownership is consistent across `build-parallel`, `build-dispatch`, and `build-execution` (apart from item 7).
- S6, S7, S11, S12, D4 (docs, explore, prototype): confirmed fixed in the current files.
- `source_hash` algorithm in `spec-format.md` matches `conclusion.rs` byte for byte.
- Installers: managed mode, ownership markers, and retired-link cleanup behave as documented.

## Not covered

- Live model-driven evals (`run-evals.sh`, `run-output-evals.sh`) were not run.
- Knowledge flows `reconcile` and `reflect-distill` were read but not exercised.
- `plan-splitting` clusters and `build-decomposition` expand/migrate/contract were read but not run on a multi-package repo.
- Sandbox-denial fallback (retry once, then degrade) was checked in the text only.

## Incidental

During the audit, one reviewer wrote a test entry to the real `~/.config/varde/paths.toml` and removed it right away with `paths unset`. A check afterwards found no leftover entry (22 project entries, no temp paths).

## Resolutions (2026-09-25)

- **A. One store per repo (items 1, 5).** Working lives only at the path configured in
  `~/.config/varde/paths.toml` (`.../Agent Memory/varde/working`). `find_root` resolves to
  the main checkout's git top level; nested `memory-bank/` dirs and linked worktrees no
  longer create separate projects. Merge the `code-cli`, `workflow-cli`, `skills` vault
  stores and the stray in-repo `memory-bank/working/` into it; drop their `paths.toml`
  entries (and `varde-worktrees`). Knowledge stays committed: merge `code-cli/` and
  `workflow-cli/` knowledge into root `memory-bank/knowledge/`. Update root `AGENTS.md`.
- **Config adherence.** Skills never resolve paths themselves: one vendored block runs
  `varde-workflow paths --json` and passes absolute `<working>`/`<knowledge>` into
  subagent briefs. If `paths` can't run: retry once escalated, then ask the user for the
  path; never fall back to `memory-bank/`. Tests: CLI resolution (worktree, module subdir,
  vault artifact); skills block identical and no stray `memory-bank/` paths; an eval that a
  new plan lands in the configured path.
- **CLI install.** `varde sync` builds and installs `varde-code` and `varde-workflow` by
  default (`cargo install --path`, reusing workspace `target/`); `--no-cli` opts out and
  only reports missing CLIs; `--dry-run` lists the cargo commands. No `cargo` → fail
  before writing anything, pointing to rustup or `--no-cli`.
- **B. Conclusions (items 2, 11, 12).** `plan:` stores the plan id. Lint skips orphan
  checks for `conclusions/` and `promotions/`. Conclusions use `<date>-<slug>.md`
  (`git mv`); rewrite existing `plan:` fields, scrubbing absolute paths.
- **C. CHANGELOG (item 9).** `build-plan-finish` adds an `Unreleased` entry when the touched
  module has a CHANGELOG; `varde-docs refresh` owns release-time curation (drop exclusion).
- **Clear fixes, no decision needed:** 3, 4, 6, 7, 8, 10, 13-17.

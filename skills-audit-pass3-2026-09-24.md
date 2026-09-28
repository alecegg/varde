# Flow walkthrough, pass 3: varde skills (2026-09-24)

## How to read this

Three reviewers walked every flow end to end: SKILL.md routing → references read →
commands and scripts run → artifacts → handoff. **Checked** = confirmed directly in
source during consolidation; **Repro** = reproduced by a reviewer in a temp repo.
**Clear** = one fix preserves intent. **Decision** = needs a user choice; see
Resolutions.

Baseline: `check-refs.sh` passes; all 10 `skills/tests` and 7 `agents/tests` pass;
every cited `varde-workflow` / `varde-code` command and flag exists;
`validate-frontmatter.py` OK on all 7 skills.

## Breaks work or loses data

- **F1 — Clear. Checked, Repro.** `varde-change/scripts/resolve-execution-wave.py:42` matches only indented list items (`^\s+-`). `varde-workflow transition` writes unindented `- dep`, so `depends_on`/`modifies`/`creates` parse empty and a dependent is dispatched before its dependency. Fix: `^\s*-\s+` while in a list key; add an unindented fixture to `tests/parallel-wave-scheduler.sh`.
- **F2 — Decision (D1). Repro.** Parallel waves: `build-parallel.md:13-15` has executors update task files in the main checkout; `build-execution.md:66-67` has them commit the task file on their branch. Merge fails with exit 4, which `build-parallel.md:22-23` doesn't document; its next step runs `worktree-cleanup.sh`, force-deleting the unmerged branch. "Start from a clean tree" can never hold between waves.
- **F3 — Clear. Checked, Repro.** `varde:110` always passes `-f` to `skills/install.sh`, whose `install_skill` `rm -rf`s any existing `varde-*` dir, marker or not. Fix: managed mode (`-m`) for skills mirroring agents; `varde init` uses it.
- **F4 — Clear. Repro.** `agents/install.sh` default and `-f` installs write no ownership marker, so `varde init -m` preserves them forever as unowned. Fix: always write the marker.
- **F5 — Clear. Checked.** `varde-code scan` caps at 100 findings (`scan_cli.rs:19`); `varde-review/references/scan.md` never mentions `findings_summary.truncated` or `findingsOffset`. Fix: check `truncated`, page until `shown == total`, group via `findings_summary.by_rule`.
- **F6 — Clear.** `scan --apply` applies every rewrite-rule match (no rule filter, ignores severity threshold). Fix in `scan.md:45-48`: suppress not-real rewrite findings before `--apply`, or fix by hand.
- **F7 — Clear. Checked, Repro.** `detect_changes` `diffMode: working_tree` is plain `git diff` — misses untracked and staged-only. Affects `report.md:18-20`, `simplify.md:18`, `varde-review/references/varde-code.md:36-37`. Fix: `diffMode: "range", range: "HEAD"` plus `git ls-files --others --exclude-standard`.
- **F8 — Clear. Repro.** Finalize's `git mv` (`plan-fundamentals.md:27`) fails (exit 128) on a never-committed or ignored draft. Fix: plain `mv` unless tracked. Make `evals/setup-change-eval.sh` cover the uncommitted case.
- **F9 — Decision (D3).** With tracked plan storage, `varde-review fix mode=build` hard-stops on a dirty tree: the `active` transition (`build-plan-run.md:36`) and the nested review folder are uncommitted. The review-fix round's edits are never committed either.

## Flows that dead-end or contradict

- **F10 — Clear.** Orchestrator picks a posture per task (`build-plan.md:39-51`) but the dispatch brief (`build-dispatch.md:37-39`) doesn't carry it and `build-execution.md` never loads posture references; `build-execution.md:27` contradicts the refactor posture. Fix: `posture` in brief; executor loads the matching posture reference; spikes skip commit.
- **F11 — Clear.** After Skip, dependents stay `todo`, resolver returns an empty wave, loop never ends (`build-dispatch.md:19-20`, `build-plan-run.md:43-48`). Fix: empty wave ends the loop; report remaining `todo` as skipped/blocked_by_dep.
- **F12 — Clear.** `agents/review/claude.md:18-28` always creates a review folder and writes; `report.md:65-70` has chunk subagents write nothing. Over budget it's told to split, with no Agent tool. Cites nonexistent `--mode full`; "section-category pair" undefined. Fix: chunk-delegate branch; over budget → report back; regenerate from `agents/capabilities.json`.
- **F13 — Clear.** `agents/plan/claude.md`: lacks `Edit`; commits unconditionally; claims `varde-workflow` is the write path; routes ready plans to the executor; Finalize has it spawn another agent (nested). `agents/executor/claude.md`: unconditional simplify vs the ~40-line threshold. Fix: align with skill; plan agent does finalize work itself.
- **F14 — Decision (D2). Repro.** `varde-workflow paths --json` roots at the cwd when no `memory-bank/` exists, so running from a subdir writes notes/reviews/handoffs there. Gotcha repeated in `varde-review/SKILL.md:22`, `varde-knowledge/SKILL.md:23`, `varde-docs/SKILL.md:17-21`.
- **F15 — Clear.** Handoff resume (`reflect-handoff.md:71-74`) uses `git log` on `<working>` links that are outside git or ignored, so they always read `unchanged`. Fix: mtime vs handoff `timestamp` for `<working>` targets.
- **F16 — Clear. Checked, Repro.** `varde-prototype/evals/verify-prototype-eval.sh:8` uses `mapfile` (absent in macOS bash 3.2, exit 127); line 25 checks `logic.html` only in cwd. Fix: portable loop and `find`; add a verifier test.

## Smaller issues

- **S1 — Clear.** `check-refs.sh:62-99` ignores `../`, `varde-*/` prefixes, markdown links, `assets/`. Fix: fail on those; check link targets.
- **S2 — Decision (D4).** Explore's description offers "compare design options … as an HTML page" with no route; prototype's "Not for comparing options in chat" implies it owns HTML comparisons.
- **S3 — Clear.** Diagnose-only ("why does this test fail?") likely triggers explore, not varde-change; varde-review lacks a "Not for" clause (overlaps doc-authoring on SKILL.md review). Tighten descriptions; add boundary queries.
- **S4 — Clear.** varde-change: `readiness` misses cycles (use `graph`); resume re-runs `active → active` (guard); build offers `-draft` plans; verify stops at a group parent; post-conclusion action names undocumented; TASK-TEMPLATE `depends_on` defaults to `[]`; `out_of_scope` field vs heading; final plan id keeps date prefix; draft detection says "a bullet"; inline without executor still runs the task cycle; debug commit order; friction points at `varde-knowledge`; review brief carries execution location; finish's nested-child check becomes a precondition.
- **S5 — Decision (D5).** `varde-workflow lint` flags `missing_index` as an error; `varde-knowledge/references/note.md:21-22` says don't create `index.md` unless asked. Spec lint is mostly `orphaned_concept` noise.
- **S6 — Decision (D6).** `varde-docs spec.md` / `spec-format.md` describe an architecture document no step generates or names.
- **S7 — Clear.** varde-docs: add a named-domains path (no orphan deletion) for plan-finish; load `spec-format.md` unconditionally; first-run domain discovery rule; `refresh.md` step order, quoted `repoRoot`, define `docPath`; eval 3 references a removed constraint.
- **S8 — Clear.** varde-review: plain reviews shouldn't ask for a spec (check internal consistency); define `<review-id>`/`<fix-id>`, nesting rule, status values; `plan-start.md:35` scans nested reviews; `scan.md` points `remediation` at `data.rules.<rule_id>`; whole-codebase offer vs 3×60k cap; executor restricted to `fix mode=build`.
- **S9 — Clear.** varde-knowledge: "finding" → "fact" in routing; consistent full `head_sha`; define handoff ID as folder name.
- **S10 — Clear.** Installers/validators: `install.sh` fails silently without TTY and `-f` (check `[ -t 0 ]`, dedupe `-s`); `validate-frontmatter.py` accepts folded/blank descriptions; `tests/varde-init-test.sh` bare `mktemp -d`; `varde init` exits 0 when it did nothing.
- **S11 — Clear.** varde-explore: `varde-code.md` lacks `blast_radius`/`dependents`/`tests_for_file`; agent's "build index first" is wasted; `explain.md` "document to keep" goes to `$TMPDIR`; chat mode has no instructions; evals 3–5 lack setup.
- **S12 — Clear.** varde-prototype: `style.css` per version; round/version numbering; "outside the repo" wording; eval runner never sets `EVAL_RUN_START`.
- **S13 — Clear.** varde-agent-doc-authoring: one home for the final-pass rule; `specification.md` always read when authoring; triggering row reads sibling descriptions; `uv run` path from any cwd.
- **S14 — Decision (D7).** `varde init` has no pi harness support; scope of this fix round.

## Resolutions (walkthrough)

One entry per decision, in order. **Decided** = the user chose among options.

- **D1 (F2) — Decided: orchestrator is the sole task-file writer in parallel waves.** Executors in a parallel wave never write or commit their task file; they return status (`done`/`blocked`) plus evidence in their report. After merging the wave, the orchestrator applies each transition and commits task-file updates (tracked storage) before the next wave. Serial/inline execution unchanged: the executor still updates its own task file. `build-execution.md` gets one line: "In a parallel wave, report status; do not write the task file." Independent of the choice: `build-parallel.md` documents merge exit 4 as "stop; do not run cleanup; keep the branch." Rejected: pre-committing `in_progress` before dispatch (two rules depending on storage), executor-owned task files (no in-progress visibility, no record on crash).
- **D2 (F14) — Decided: fix in the CLI.** `workflow-cli/varde-workflow/src/commands/paths.rs:162` `project_root` (no `--project`) resolves in order: nearest `memory-bank/` ancestor → a `paths.toml`-configured project whose root is an ancestor of cwd → main git worktree top-level (parent of `git rev-parse --git-common-dir`, so linked worktrees map to the main checkout) → cwd. Check other no-flag root fallbacks (`okf-core/src/memory.rs:338` `find_root`, `okf-core/src/vault.rs:47`) use the same chain. Add tests in `varde-workflow/tests/memory_paths.rs`: subdir with no memory-bank; subdir with a configured redirect; linked worktree. Skills unchanged. Also found: from a subdir the `paths.toml` redirect key misses, so output landed in-repo instead of the redirected location. Rejected: skill-side `--project "$(git rev-parse --show-toplevel)"` (repeated per skill, misses other commands, wrong in worktrees).
- **D3 (F9) — Decided: commit plan bookkeeping when it happens (tracked storage).** Rule: with tracked plan storage, each step commits the plan artifacts it changes. Sites: `active` transition (`build-plan-run.md:36`, before the first task/wave); task-file updates after each parallel wave (D1); review folder after `report` writes it (`build-plan-finish.md` step 1); the build-mode fix round commits its code edits once at round end (`build-plan-finish.md` step 2 / `varde-review/references/fix.md`). The existing end-of-run "commit the plan's status change" stays for `completed`. Build-mode fix keeps its strict dirty-tree check. Also fixes `build-parallel.md` step 1 "Start from a clean tree". Ignored or outside-repo storage: no change. Rejected: exempting `<working>/` from the dirty check (every clean-tree check would need the exception; would mask bookkeeping bugs).
- **D4 (S2) — Decided: explore owns written HTML comparisons.** `varde-explore/references/explain.md` target-shape table gains an "options" shape (a set of named alternatives or a design question) with sections Options, Tradeoffs, Recommendation; same `$TMPDIR/<date>-<slug>.html` output. `varde-explore/SKILL.md` row 2 widens to "explain a diff or code area, or compare options, as a document to keep". Description stays true as written. Prototype unchanged (mockups and clickable models). Add `eval-tools/query-sets/sibling-boundaries.json` queries: prose comparison as HTML → explore; visual mockup variants → prototype. Rejected: routing to prototype (wrong tool for non-visual comparisons), dropping HTML comparisons (no keepable decision record).
- **D5 (S5) — Decided: fix lint to fit the skills, and strip OKF, docwatch, the Personal vault, and legacy migration.** One `workflow-cli` cleanup round:
  - **Lint** (`okf-core/src/lint.rs`): links from `index.md` count toward incoming links; `MissingIndex` becomes opt-in; `OrphanedConcept` becomes a warning. Lint reports real breakage (broken links, malformed frontmatter). varde-knowledge `note.md:21-22` ("don't create `index.md` unless asked") stays.
  - **Remove OKF conformance**: `lint --okf` and `check_okf` (required `type`, §5.4 status enum, structured-field shape, reserved-filename masking). Skills: drop "OKF v0.2 Knowledge Bundle" (`varde-knowledge/references/note.md:12`) and `--okf` (`varde-docs/references/spec.md:31`). Reword `workflow-cli/README.md` from "OKF implementation" to markdown document management. Mark `workflow-cli/memory-bank/knowledge/decision/okf-conformance-strict.md` superseded (keep history).
  - **Rename `okf-core` → `md-core`** (crate, dir, `use okf_core::` imports, `Cargo.lock`, docs, `AGENTS.md`).
  - **Remove docwatch**: `docwatch/` crate and workspace member; `varde-change/references/plan-docwatch.md` and its routing (`plan-start.md:9,17`); `workflow-cli/memory-bank/knowledge/reference/docwatch.md`; mentions in root `README.md`, root `AGENTS.md`, `workflow-cli/README.md`, `memory-bank/knowledge/decision/cli-machine-output-envelope.md`.
  - **Remove the Personal vault** (`~/.varde-workflow/`): search and lint operate on `<knowledge>` only; `--vault` removed from `concept`/`lint`; skill mentions removed (`varde-knowledge/references/varde-workflow-cli.md:19`, `note.md:6,87`, `varde-docs/references/spec.md:31`). Retire/supersede knowledge notes `definition/personal-vault.md`, `definition/project-vault.md`, `reference/vault-layering-merge.md`, `decision/bundle-merge-precedence.md` as they become false.
  - **Remove legacy artifact handling**: `inspect` and `migrate` commands, `varde-workflow/src/migration.rs`, the `legacy` detection/flag in validate (the pass-2 false positive on template-made plans goes with it).
  - Out of scope for this round (already clear): nothing else in `varde-workflow` changes.
- **D6 (S6) — Decided: generate the architecture document from the files that define the architecture.** Architecture is often declared in discrete files (infrastructure as code, deployment/orchestration config, workspace manifests), so it can carry real provenance.
  - **Sources:** the agent identifies whatever files in the repo declare deployed units, their wiring, and package/workspace structure — any IaC or config format; the skill names the category, not a list of tools or extensions. Those files are hashed as `sources` (staleness works like a domain spec). Entrypoint/handler code those files reference is read to map units to domains but not hashed; domain specs own it.
  - **Content:** Overview, Components (each deployed or packaged unit and the domain spec owning its code), Wiring (how units connect and trigger each other), Dependency Constraints, Invariants. Replaces "Layer Model"; drop the UI/middleware/domain/model layer classification in `spec-plan.md:20`.
  - **File:** `<knowledge>/specs/architecture.md`, `domain: architecture`, in the index; exempt from orphan deletion; plans may list it in `observed_specs`.
  - **No architecture-defining files found:** skip and say so; never infer architecture from folder layout.
  - **Refresh:** every full run; incremental runs when a hashed architecture source changed or a domain was added/removed.
  - Edit `varde-docs/references/spec.md` (new step after domain generation), `spec-format.md` (architecture section spec), `spec-plan.md` (source identification, refresh trigger). Rejected: removing it (the user: IaC makes architecture concrete and hashable), hand-maintained (drifts silently).
- **D7 (S14) — Decided: arbitrary install targets instead of per-harness support.** No pi-specific code. `varde init` accepts caller-given targets and passes them to the module installers, which already take `-d`:
  - `--skills-dir <path>` → `skills/install.sh -d <path>` (managed mode per F3). Repeatable.
  - `--agents-dir <path> --agent-format <claude|codex|opencode>` → `agents/install.sh -t <format> -d <path> -m`. Format is required with a custom agents dir (the installer must pick `claude.md` / `codex.toml` / `opencode.md`). Repeatable as pairs.
  - Custom targets are installed alongside (or, with `--agents` omitted and only custom targets given, instead of) detected harnesses. Not persisted: re-runs take the same flags. Document in `varde --help` and root `README.md`, with pi (`--skills-dir ~/.pi/agent/skills`) as the example. Add cases to `tests/varde-init-test.sh`.

### Walkthrough outcome

- **Scope — Decided: two plans, in order.**
  1. **workflow-cli cleanup:** D5 (lint fixes; remove OKF conformance, docwatch, Personal vault, `inspect`/`migrate`/legacy detection; rename `okf-core` → `md-core`) and D2 (project-root resolution).
  2. **Skills, agents, installers:** F1–F16, S1–S14, D1, D3, D4, D6, D7 — written against the cleaned CLI (skills drop `--vault`, `--okf`, docwatch references).
  Built by executor subagents, max 3 concurrent, no nested subagents.

---
verdict: changes-requested
reviewer: claude:varde-reviewer
base: a9f2ccd
head: a9f2ccd
---

# Plan review: sample-workflow (one round, report only)

Counts: 2 high, 6 medium, 4 low (12 findings).

## High

### WF-001 [high] Lifecycle and lint tasks re-port commands md-core already owns
Plan Decision: `knowledge *` and `setup paths` belong to md-core. But `lifecycle` owns create/update/set_field/delete/list/show/maps/search (previous `ConceptCommand`, routed as `knowledge concept` by `clis/varde/src/router.rs:136`) and `artifact-schema-graph` owns `commands/lint.py` (routed as `knowledge lint`, router.rs:137). `python/varde-md-core` already has `cli.py` (concept create/show/update/list/delete/search/set-field, lint, paths), `crud/*`, `maps.py`, `lint/`, `cmdbase/`. The router's `plan` route denies `concept, lint, paths, instructions, hook, msg`, so none of these are `plan` commands. Real workflow `plan` commands: validate, graph, check-task-ownership, execution-wave, readiness, status, now, owner, watch, conclude, distill. Question (no cut made): drop `commands/{create,update,set_field,delete,list,show,maps,search,lint}.py` and tests from workflow, leaving `lifecycle` as conclusion/owner/conclude/distill (rename it)? `commands/error.rs` (366) and `common.rs` are partly concept-oriented; `base` should state what md-core `cmdbase` already covers. `commands/paths.rs` (252) is md-core's but is not listed as excluded anywhere.

### WF-002 [high] Behavior check task is underspecified and cases/goldens do not exist
`test suite compare --module workflow` works (behavior check_dir = `python/varde-workflow/tests/behavior check`, entry point `workflow` exists, launcher calls `module.run(argv, None)`), but `python/varde-workflow/tests/` does not exist: no `cases.json`, `golden/`, or `harness.py`. The task gives no case count, no gen step, no reference implementation check, and a small case set still ends `mismatches: 0`. Needed: (a) the explicit `test suite gen --module workflow --reference implementation /Users/alec/source/varde/clis/target/release/varde` step (verify the binary exists); reference implementation argv has `plan`/`msg` prefixes that the module argv lacks, so cases need `args` vs `python_args`; (b) `--min-cases N` in the assert (compare supports it) plus a per-command group list so no command is uncovered; (c) a `harness.py` with `prepare_case` for the throwaway git repo (execution-wave, check-task-ownership), `watch` first-N-frames (`--once` or frame cap) and time/pid normalization; (d) cases for `--no-wake`/wake_command, `msg` cursor files and the `--handoff` deprecation warning. Fixture generation needs no Python code, so it could start in wave 1 (question, not a cut).

## Medium

### WF-003 [medium] pyproject lacks varde-md-core and is owned by the last task
`python/varde-workflow/pyproject.toml` depends only on `varde-core, contracts package`; every task imports `varde_md_core`. `cli-and-help` owns the pyproject and runs last, so earlier tasks' pytest cannot rely on a clean env (a workspace venv may mask it). Move the dependency edit to `base`; leave `cli-and-help` owning module/cli/help only.

### WF-004 [medium] Module surface is not stated
Plan says Module "routes `plan *`, `msg send|read`, `setup instructions`". The `plan` route denies `instructions`, `hook`, `msg`; `msg` is routed top-level. State the exact argv surface (previous `Command` list) in plan and `cli-and-help`, and confirm with app-shell/app-setup who routes `setup instructions`. `lib.rs` also exports `pub mod execution_wave` and `cli_command()`; no external use found in `clis/`, so say so.

### WF-005 [medium] Plan acceptance criteria 1 and 4 are identical; 3 already true
Criterion 4 repeats criterion 1's assert verbatim, and the "cross-read both ways" claim has no assertion (Python-write -> previous-read needs the reference implementation). Criterion 3 passes today with the skeleton (entry point already declared); assert instead that the loaded module is not the stub. Missing criteria: the hook helper API (`SETUP_WARNING, within, WithinError, has_managed_block, Message, commit_cursor, read_all, read_unread, owned_plan_id`) importable; cursor-file byte equality against a committed previous-written fixture; the "hook-path imports nothing heavy" constraint (no task asserts it, e.g. `sys.modules` check after importing `varde_workflow.inbox`); help snapshots equal reference implementation help (cli-and-help assert is just "test_cli.py exits 0").

### WF-006 [medium] Task asserts are bare "pytest exits 0"
Each assert runs a test file the task itself creates; a one-test file passes. Add minimum content and a count floor, and name the previous tests to mirror: `tests/plan_owner.rs`, `plan_wake.rs`, `plan_watch.rs`, `plan_help.rs`, `execution_wave_scenarios.rs`, `workflow_suite/status_derivation.rs` and in-file unit tests (2.2k test lines are cited by no task).

### WF-007 [medium] previous-file inventory gaps
Mapped: artifact, workflow_schema, workflow_graph, validate, graph (artifact-schema-graph); conclusion, owner, conclude, distill (lifecycle); task_ownership, execution_wave{,_paths,_tools} and their commands (ownership-and-waves); status, readiness, now; watch{,_state,_cache,_block}; msg, wake, hook; instructions; output, common, error, input (base); cli.rs. Unassigned: `src/lib.rs` (114: `run`, `--handoff` deprecation warning, `dispatch`, re-exports) - add to `cli-and-help`. `now.rs::run_watch` (the `Command::Watch` dispatch) lives in a file owned by status-readiness-now while `watch` depends on that task; state that ownership explicitly. `cmdbase` has common/errors/input/output but no `commands/error` equivalent; confirm base mapping. `commands/paths.rs`, concept commands, lint: see WF-001.

### WF-008 [medium] Wave independence and sizing
After `base`, five tasks run in parallel and `commands/__init__.py` is owned by `base`, so later tasks cannot register modules: make it empty and have `cli-and-help` own routing (say so). `watch` may need `owner` (lifecycle) via watch_state; verify and add the dependency. `status.rs` (1991) and watch (2.9k) are single tasks; offer splits as a question. `instructions` uses md-core `load_config/save_config/Orchestration/RoleCaps`: `Orchestration` exists in `memory_config.py`; confirm the others. Critical chain base -> artifact -> status -> watch -> cli -> behavior check is fully serial.

## Low

### WF-009 [low] Migrate and sizing
No plan/task text covers `migrate` (grep clean; the only hit is "migration" in the dual-run Constraint). Plan Problem says 12.6k lines; excluding concept/lint/paths the port is about 10.4k src lines.

### WF-010 [low] Assumptions understate risk
Only the git-fixture assumption is listed. Add: md-core memory/config API reliance; the external `wake_command` subprocess (needs a fake command in fixtures); watch stale detection depends on mtimes and wall clock (normalization); msg cursor file locking semantics.

### WF-011 [low] app-glue only needs hook helpers
`app-glue` needs `inbox`, `instructions`, `status.owned_plan_id`, not the CLI. Record that it could start after those tasks (question, no change).

### WF-012 [low] Shippability
Intermediate merges keep the stub `module.py` (exit 2), so nothing routes to Python workflow before app-shell flips; say so. The stub `register()` stays valid until `cli-and-help`.

## Questions (no scope changed)

1. Drop concept/lint from workflow tasks (WF-001)? Recommended yes.
2. Split `status` and `watch` tasks (WF-008)?
3. Start behavior check fixture and golden generation in wave 1 (WF-002)?

## Re-check

Verdict: ok. `varde plan validate` passes on plan.md and all 10 tasks (only style warns).

- WF-001: concept/lint/paths tasks gone; Non-goals and lifecycle/artifact tasks state md-core owns them. No dangling depends_on; cli-and-help depends on all 7 remaining tasks; no owns overlaps.
- WF-002: behavior check task has gen step with reference implementation path, args vs python_args, harness.py, `--min-cases 40`; plan criterion 1 matches. Minor: "cross-read plan files both ways" still has no assert (non-blocking).
- WF-003: base owns pyproject.toml and adds varde-md-core; cli-and-help no longer owns it.
- WF-004/007: plan states module surface; cli-and-help owns lib.py and run_watch dispatch routing.
- WF-005: criteria 4 (hook API + sys.modules) and 5 (cursor bytes) added; help snapshots + 15-test floor in cli-and-help.
- WF-008: base keeps commands/__init__.py empty; cli-and-help owns routing. Watch needs no lifecycle dependency (previous watch only reads plan.owner and msg state, not the owner command).
- WF-010, WF-012: assumptions and stub-module decision present.

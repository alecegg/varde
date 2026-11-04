---
status: active
title: "sample-workflow: port varde-workflow (plan/task lifecycle, status, execution waves, task ownership, watch, inbox, instructions) to Python"
type: plan
depends_on: [sample-core, python-port-md-core]
shared: [uv.lock]
reviewed_commit: a9f2ccd
reviewed_on: 2026-10-14
owner: claude:sample-workflow
branch: worktree/sample-workflow
---

## Problem

`varde plan`, `varde msg` and `setup instructions` (12.6k previous lines) drive every orchestration session; they read plan files through md-core and must produce byte-identical JSON/text for status, validate, execution-wave and watch.

## Solution

A `varde-workflow` package ports all workflow commands on top of `varde_md_core`, with the hook-facing inbox helpers the app's hook dispatch imports, proven against reference implementation goldens built from fixture plan stores.

## Non-goals

- Knowledge store and `setup paths` (python-port-md-core)
- Hook installation (python-port-app-setup)
- Concept CRUD, maps, search and lint commands (md-core owns them; user decision 2026-10-14)
- Changing plan formats or statuses
- `migrate` (dropped by user decision 2026-10-14)

## Constraints

- previous repo `/Users/alec/source/varde` (renamed `previous implementation` at cutover) is read-only; goldens come only from the reference implementation `/Users/alec/source/varde/clis/target/release/varde` through `test suite gen` and are committed, so `compare` never needs the reference implementation path
- SQLite schemas, file formats, paths and JSON key order identical to previous — previous and Python read the same stores during migration
- Python >=3.14, no native extensions of our own at first (reopening is an explicit per-module user decision); third-party dependencies are the set core declares in each package's pyproject (extra ones go in plan `shared:` and need a one-line reason in the task Progress)
- Imports only as allowed by `python/varde-core/API.md`; only the app package depends on module packages
- Hook-path code (anything `varde capture --hook`, `varde note` or `varde event` reaches) imports nothing heavy at module import time
- Help text is a committed snapshot rendered verbatim (generated once from the reference implementation), not rebuilt from the parser
- Measured runs hold `/Users/alec/source/.varde-measure.lock`, use `ioreg` only, N>=30 for wall time, N>=5 for `ioreg` write bytes, record load, retain every run, no quiet-machine gating
- `watch` is long-running: behavior check compares the first N output frames from a scripted fixture, not live time
- Plan-store fixtures are copied from a frozen snapshot of a real plan set, never read from the live working store

## Design

### Tech choices

- Package `python/varde-workflow` (`varde_workflow`); `commands/` subpackage with one file per previous command so tasks own whole files

### Schema / data model

(none)

### API / interface contracts

- `varde_workflow.module.Module` (`name="workflow"`): routes `plan *`, `msg send|read`, `setup instructions`
- Library for the app hook: `SETUP_WARNING`, `within`, `has_managed_block`, `commit_cursor`, `read_unread`, `owned_plan_id`

## Decisions so far

- Until `cli-and-help` lands the stub `module.py` stays, so nothing routes to Python workflow before app-shell flips

- `knowledge *` and `setup paths` belong to md-core even though previous hosts them in workflow → keeps ownership disjoint

## Open Questions

n/a — no open questions

## Assumptions

- Execution-wave and task-ownership output depends on git state; fixtures use a throwaway git repo built by the harness — affects: behavior check cases — confidence: high
- md-core memory/config API (`load_config`, `Orchestration`, `RoleCaps`) covers `instructions`; the `wake_command` subprocess is a fake command in fixtures; watch stale detection depends on mtimes and clock, so behavior check normalizes them; msg cursor locking matches previous — affects: inbox, instructions, watch — confidence: medium

## Acceptance criteria

- [ ] Given the reference implementation goldens for `workflow`
      When the behavior check compare runs
      Then every case matches after documented normalization
      (assert: `cd /Users/alec/source/varde-py && uv run python -m test suite compare --module workflow --min-cases 40` → exit 0 and last line `mismatches: 0`)
- [ ] Given the package tests
      When pytest runs
      Then they pass
      (assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/ -q` → exit 0)
- [ ] Given the module is installed
      When `old_contracts` discovery lists it
      Then `workflow` resolves through the `varde.modules` entry point
      (assert: `cd /Users/alec/source/varde-py && uv run python -c "from importlib.metadata import entry_points as e; print(sorted(x.name for x in e(group='varde.modules')))"` → output contains `'workflow'`)
- [ ] Given the hook-facing library
      When it is imported
      Then `SETUP_WARNING, within, WithinError, has_managed_block, Message, commit_cursor, read_all, read_unread, owned_plan_id` exist and importing `varde_workflow.inbox` loads no heavy module
      (assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/test_inbox.py -q` → exit 0, including a `sys.modules` check)
- [ ] Given a previous-written msg cursor file
      When Python reads and commits it
      Then bytes equal the committed previous-written fixture
      (assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/test_inbox.py -q -k cursor` → exit 0)

## Progress

## Related

- Inventory: /Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-14-varde-python-port/notes/port-plan.md
- /Users/alec/source/varde/clis/workflow/varde-workflow

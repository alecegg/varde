---
type: task
status: done
depends_on: [artifact-schema-graph, ownership-and-waves, status-readiness-now, lifecycle, watch, inbox, instructions]
owns: [python/varde-workflow/src/varde_workflow/cli.py, python/varde-workflow/src/varde_workflow/module.py, python/varde-workflow/src/varde_workflow/help/**, python/varde-workflow/src/varde_workflow/lib.py, python/varde-workflow/tests/test_cli.py]
---

Port `cli.rs` (856) routing and `lib.rs` (`run`, `--handoff` deprecation warning, dispatch; also `now.rs::run_watch` dispatch is routed here), the exact argv surface of the previous `plan`/`msg` commands (`setup instructions` routing confirmed with app-shell/app-setup), commit help snapshots, register the `workflow` entry point.

#### Acceptance criteria

- assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/test_cli.py -q` → exit 0 and at least 15 tests passed, including help snapshots equal to the reference implementation help for every command

#### Progress

- `varde_workflow.module.register() -> WorkflowModule`; `WorkflowModule.run(argv: list[str], io: Io | None = None) -> int`; `WorkflowModule.help(path: str = "") -> str`.
- `varde_workflow.cli.run(argv: list[str], io: object = None) -> int`; `help_text(path: str = "") -> str`. `varde_workflow.lib` exports `SETUP_WARNING`, `within`, `WithinError`, `has_managed_block`, `Message`, `commit_cursor`, `read_all`, `read_unread`, and `owned_plan_id`.
- Generated 19 plan/msg/setup-instructions help snapshots from the previous reference implementation; all compare byte-for-byte. `uv run pytest python/varde-workflow/tests/test_cli.py -q` -> 37 passed, covering snapshot lookup, routing, and `--handoff` deprecation. The test caught and fixed the inbox `MemoryPaths` import.


---
type: task
status: done
depends_on: [base, artifact-schema-graph]
owns: [python/varde-workflow/src/varde_workflow/commands/status.py, python/varde-workflow/src/varde_workflow/commands/readiness.py, python/varde-workflow/src/varde_workflow/commands/now.py, python/varde-workflow/tests/test_status.py]
---

Port `commands/status.rs` (1991), `readiness.rs`, `now.rs`.

#### Acceptance criteria

- assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/test_status.py -q` → exit 0

#### Progress

- `varde_workflow.commands.status.collect_from(working: str | Path, now: float | None = None, stall_minutes: int = 60) -> dict[str, Any]` returns the previous-compatible status rollup; `render(report, time_text) -> str`, `count_open_questions(body: str) -> int`, `stalled_minutes(now, last_activity, threshold) -> int | None`, `load_stall_minutes() -> tuple[int, str | None]`, `staleness_notice_for(plan_path, repo=None) -> str | None`, and `staleness_notices(working, repo=None) -> list[str]` cover status formatting, task progress, config, and review staleness.
- `varde_workflow.commands.readiness.readiness_data(path: str) -> dict[str, Any]` augments graph readiness with `planning_ready` and `implementation_ready`; `run(args) -> int` renders JSON or pretty text.
- `varde_workflow.commands.now.normalize_line(value: str) -> str`, `plan_key(plans_dir: Path, plan_path: Path) -> str`, `read_plan_id(path: Path) -> str`, `resolve_plan(argument, cwd, plans_dir) -> Path`, `write_line(path, line) -> None`, `read_line(plans_dir, plan_path) -> str | None`, and `run(args) -> int` implement the independent, atomic plan-now store. `owned_plan_id` remains in `inbox.py`, owned by the inbox task.
- Check: `uv run pytest python/varde-workflow/tests/test_status.py -q` -> 3 passed; `git diff --check` clean.


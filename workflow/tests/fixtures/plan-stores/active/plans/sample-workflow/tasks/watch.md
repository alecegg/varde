---
type: task
status: done
depends_on: [base, status-readiness-now]
owns: [python/varde-workflow/src/varde_workflow/commands/watch.py, python/varde-workflow/src/varde_workflow/commands/watch_state.py, python/varde-workflow/src/varde_workflow/commands/watch_cache.py, python/varde-workflow/src/varde_workflow/commands/watch_block.py, python/varde-workflow/tests/test_watch.py]
---

Port the four watch files (about 2.9k lines): state, cache, stale detection, the generated block written to session notes.

#### Acceptance criteria

- assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/test_watch.py -q` → exit 0

#### Progress

- `watch.fixture_frames(fixtures, *, limit: int, clock: Callable[[], float], threshold: int = 60) -> Iterator[tuple[float, list[Event]]]`; `run_frames(fixtures, *, limit, clock, json_output=False, threshold=60) -> list[str]` renders only the first N fixture frames with injected time. `run_watch(args, *, frame_limit=None, clock=time.time, sleep=time.sleep) -> int` supports bounded tests; `frame_events(snapshot, now, threshold, previous=None) -> tuple[list[Event], WatchCache]`. `scan(working, repo, now, threshold_secs=1200) -> list[dict[str, Any]]` gathers plan snapshots.
- `watch_cache`: `CachedPlan`, `WatchCache`; `cache_path_for_repo(working, notes, repo) -> Path`; `read_for_repo(...) -> WatchCache | None`; `write_if_changed_for_repo(...) -> bool`.
- `watch_block`: `PlanState`, `PlanRow`, `BlockModel`; `render(model) -> str`; `write_block(path, model) -> None`. `watch_state.model(plans) -> BlockModel`.
- Check: `VARDE_TREE_SITTER_CACHE_DIR=/tmp/varde-tree-sitter-cache uv run pytest python/varde-workflow/tests/test_watch.py -q` -> 3 passed; `uv run ruff check` on the five owned files and `git diff --check` passed.


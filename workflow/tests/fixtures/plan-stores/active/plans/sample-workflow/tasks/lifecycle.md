---
type: task
status: done
depends_on: [base, artifact-schema-graph]
owns: [python/varde-workflow/src/varde_workflow/conclusion.py, python/varde-workflow/src/varde_workflow/commands/owner.py, python/varde-workflow/src/varde_workflow/commands/conclude.py, python/varde-workflow/src/varde_workflow/commands/distill.py, python/varde-workflow/tests/test_lifecycle.py]
---

Port the conclusion commands (`conclusion.rs`, owner/conclude/distill). Concept CRUD, maps, search and lint belong to md-core (`knowledge concept|lint`), not this plan.

#### Acceptance criteria

- assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/test_lifecycle.py -q` → exit 0

#### Progress

- `conclusion`: `Conclusion(id: str, head: str)`; `ConcludeError(code: str, message: str)`; `conclude(directory: Path | str, merged: str | None = None, repo: Path | str | None = None) -> Conclusion`; `unchecked_acceptance(body: str) -> bool | None`.
- `commands.owner`: `run(args: Any) -> int`; `validate_owner(owner: str) -> None`; `resolve_plan(argument: Path | str, cwd: Path, plans_dir: Path) -> Path`; `set_owner_line(data: bytes, owner: str) -> bytes`; `remove_owner_line(data: bytes) -> bytes`; `frontmatter_bounds(data: bytes) -> tuple[int, int]`; `owner_bounds(data: bytes, start: int, end: int) -> tuple[int, int] | None`; `continuation_end(data: bytes, line_end: int, frontmatter_end: int) -> int`; `atomic_write(path: Path, data: bytes) -> None`.
- `commands.conclude.run(args: Any) -> int`.
- `commands.distill`: `Draft(markdown: str, data: dict[str, Any])`; `run(args: Any) -> int`; `distill(argument: Path | str, cwd: Path | None = None) -> Draft`; `section(body: str, heading: str) -> str`; `count_files(directory: Path) -> tuple[int, int]`.
- Check: `VARDE_TREE_SITTER_CACHE_DIR=/tmp/varde-tree-sitter-cache uv run pytest python/varde-workflow/tests/test_lifecycle.py -q` -> 12 passed; `git diff --check` -> passed.


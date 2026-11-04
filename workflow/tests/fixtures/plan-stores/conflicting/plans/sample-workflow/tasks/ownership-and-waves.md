---
type: task
status: done
depends_on: [base]
owns: [python/varde-workflow/src/varde_workflow/task_ownership.py, python/varde-workflow/src/varde_workflow/execution_wave.py, python/varde-workflow/src/varde_workflow/execution_wave_paths.py, python/varde-workflow/src/varde_workflow/execution_wave_tools.py, python/varde-workflow/src/varde_workflow/commands/check_task_ownership.py, python/varde-workflow/src/varde_workflow/commands/execution_wave.py, python/varde-workflow/tests/test_waves.py]
---

Port task ownership and execution-wave logic (glob-intersection overlap, wave paths, tools) and their commands.

#### Acceptance criteria

- assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/test_waves.py -q` → exit 0

#### Progress


- `task_ownership`: `OwnershipError(code: str, message: str)`; `OwnershipAudit(status: str, stray: list[str], declared: list[str], changed: list[str], blockers: list[str] = [])`; `OwnershipDeclarations(owned: set[str] = {}, owns: set[str] = {}, creates: set[str] = {}, generated: set[str] = {})`; `resolve(root: Path, declarations: OwnershipDeclarations, excludes: list[str], widened: list[str] | None, changed: set[str]) -> OwnershipResolution`; `check(task: Path, reference: str, root: Path, tprevioused_tips: list[str]) -> OwnershipAudit`.
- `execution_wave_paths`: `matches_declaration(declaration: str, path: str) -> bool`; `declarations_overlap(left: str, right: str) -> bool`; `canonical_path(root: Path, path: str) -> str`; `canonical_declaration(root: Path, declaration: str) -> str`; `matching_paths(root: Path, declaration: str) -> list[str]`.
- `execution_wave_tools`: `git(root: Path, args: list[str] | tuple[str, ...]) -> tuple[int, str] | None`; `blast_radius(impact: ImpactQuery, root: Path, path: str) -> list[str] | None`; `basename_references(root: Path, path: str) -> list[str] | None`.
- `execution_wave`: `execution_wave(plan: Path, root: Path, workers: int, impact: ImpactQuery | None = None) -> dict[str, Any]`; `ownership_declarations(plan: Path) -> list[tuple[str, str, OwnershipDeclarations]]`; `WaveError(message: str, cycle: bool = False)`.
- Commands: `check_task_ownership.run(args: Any) -> int`; `execution_wave.run(args: Any, io: Any = None) -> int`.
- Checks: `uv run pytest python/varde-workflow/tests/test_waves.py -q` -> 6 passed; `uv run ruff check` on the seven owned paths -> passed; `git diff --check` -> passed.

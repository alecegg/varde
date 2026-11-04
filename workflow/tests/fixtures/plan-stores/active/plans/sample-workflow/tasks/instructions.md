---
type: task
status: done
depends_on: [base]
owns: [python/varde-workflow/src/varde_workflow/commands/instructions.py, python/varde-workflow/src/varde_workflow/blocks.py, python/varde-workflow/tests/test_instructions.py]
---

Port `setup instructions` (412): managed instruction block install/remove using `varde_core.constants.toz_instruction_block`.

#### Acceptance criteria

- assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/test_instructions.py -q` → exit 0

#### Progress

- Confirmed Python md-core config APIs: `load_config() -> Config`, `save_config(config: Config) -> Path`, and `Config.document` hold the parsed TOML dict. `Config.orchestration` is `Orchestration` for wake command/timeout/failure settings only. There is no Python `Instructions` config object, `RoleCaps` type, or orchestration cap accessors/setter yet (unlike previous md-core); this task reads and updates those fields in `Config.document` and resolves caps locally.
- `varde_workflow.blocks`: `block_ranges(content: bytes) -> list[tuple[int, int]]`, `install_block(existing: bytes, block: bytes) -> bytes`, `remove_blocks(existing: bytes) -> bytes`, `has_managed_block(path: Path) -> bool`.
- `varde_workflow.commands.instructions`: `run(args) -> int`, `install(args) -> int`, `targets() -> int`, `remove(dry_run: bool = False) -> int`, `unique_targets(paths: list[Path]) -> list[Path]`, `resolved_caps(orchestration: dict) -> RoleCaps`, `render_block(caps: RoleCaps, sections: list[str]) -> str`, `orchestration_brief(caps: RoleCaps) -> str`, `install_target(path: Path, block: bytes, dry_run: bool) -> None`.
- Check: `uv run pytest python/varde-workflow/tests/test_instructions.py -q` -> 5 passed.


---
type: task
status: done
depends_on: [base]
owns: [python/varde-workflow/src/varde_workflow/commands/msg.py, python/varde-workflow/src/varde_workflow/commands/wake.py, python/varde-workflow/src/varde_workflow/commands/hook.py, python/varde-workflow/src/varde_workflow/inbox.py, python/varde-workflow/tests/test_inbox.py]
---

Port `msg.rs`, `wake.rs`, `hook.rs` and the library helpers the app hook imports; cursor files stay byte-compatible.

#### Acceptance criteria

- assert: `cd /Users/alec/source/varde-py && uv run pytest python/varde-workflow/tests/test_inbox.py -q` → exit 0

#### Progress


- `varde_workflow.inbox.Message(ts: str, from_: str, to: str, kind: str, text: str, notes: str | None = None)` provides previous-compatible line and compact JSON rendering; `read_all(working: str | Path) -> list[Message]`, `read_unread(working: str | Path, reader: str) -> tuple[list[Message], int | None]`, and `commit_cursor(working: str | Path, reader: str, offset: int) -> None` use newline-terminated JSONL and decimal byte-offset cursors.
- Hook helpers: `within(timeout: float, work: Callable[[], T]) -> T` raises `WithinError` (`TIMED_OUT` or `PANICKED`); `has_managed_block(path: str | Path) -> bool`; `owned_plan_id(path: str | Path, owner: str) -> str | None`. Imports in `varde_workflow.inbox` use only the standard library; `owned_plan_id` lazily imports md-core frontmatter parsing.
- `varde_workflow.commands.msg.append_message(from_address: str, to: str, kind: str, text: str, notes: str | Path | None = None, *, working: str | Path | None = None) -> Message` and `append_event_message(working: str | Path, from_address: str, to: str, kind: str, text: str, notes: str | Path | None = None) -> Message` implement strict user sends and sanitized watch events.
- `varde_workflow.commands.wake.WakeRunner.load() -> WakeRunner`, `.empty() -> WakeRunner`, and `.run(event: object) -> str | None` port configured wake execution. `varde_workflow.commands.hook` re-exports the three hook helpers.
- Check: `uv run pytest python/varde-workflow/tests/test_inbox.py -q` -> 3 passed; `git diff --check` clean.

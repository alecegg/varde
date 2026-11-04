from __future__ import annotations

import shutil
from pathlib import Path

from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.queue_line_sync import export_line_queue, import_line_queue

FIXTURE = Path(__file__).parent / "fixtures" / "queue_line" / "native-cutover.md"


def _plan(tmp_path: Path) -> tuple[Path, str]:
    plan = tmp_path / "working" / "plans" / "sample-plan"
    queue = plan / "notes" / "queue.md"
    queue.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE, queue)
    return plan, queue.read_text()


def test_import_is_idempotent_and_export_preserves_passthrough(tmp_path: Path) -> None:
    plan, source = _plan(tmp_path)
    first = import_line_queue(plan)
    second = import_line_queue(plan)
    assert first.added > 0
    assert second.unchanged == first.added
    assert export_line_queue(plan) == source


def test_hand_edit_is_imported_before_export(tmp_path: Path) -> None:
    plan, source = _plan(tmp_path)
    import_line_queue(plan)
    export_line_queue(plan)
    edited = source.replace("custom:value", "custom:edited")
    if edited == source:
        edited = source.replace("fix:no", "fix:yes", 1)
    (plan / "notes" / "queue.md").write_text(edited)
    rendered = export_line_queue(plan)
    assert rendered == edited
    assert import_line_queue(plan).unchanged > 0


def test_duplicate_task_ids_are_reported(tmp_path: Path) -> None:
    plan = tmp_path / "working" / "plans" / "duplicate"
    queue = plan / "notes" / "queue.md"
    queue.parent.mkdir(parents=True)
    queue.write_text("same | fix:no\nsame | fix:yes\n")
    report = import_line_queue(plan)
    assert report.conflicts == ("duplicate task id: same",)


def test_import_does_not_reset_store_state(tmp_path: Path) -> None:
    plan, _ = _plan(tmp_path)
    import_line_queue(plan)
    working = plan.parents[1]
    store = SQLiteQueue(working / ".cache/data/queue.sqlite3")
    item = store.list("line:plans/sample-plan")[0]
    store.transition(item.queue_name, item.id, "building", actor="test")
    import_line_queue(plan)
    assert store.get(item.queue_name, item.id).state == "building"


def test_same_named_plan_directories_have_independent_queues(tmp_path: Path) -> None:
    working = tmp_path / "working"
    plans = [working / "plans" / group / "shared" for group in ("a", "b")]
    sources = [
        "same-task | fix:no | custom:a\n",
        "same-task | fix:yes | custom:b\n",
    ]
    for plan, source in zip(plans, sources, strict=True):
        queue = plan / "notes" / "queue.md"
        queue.parent.mkdir(parents=True)
        queue.write_text(source)
        import_line_queue(plan)

    assert export_line_queue(plans[0]) == sources[0]
    assert export_line_queue(plans[1]) == sources[1]
    store = SQLiteQueue(working / ".cache/data/queue.sqlite3")
    left = store.get("line:plans/a/shared", "line:plans/a/shared#same-task")
    right = store.get("line:plans/b/shared", "line:plans/b/shared#same-task")
    assert left.extra is not None and right.extra is not None
    assert left.extra["task"] == right.extra["task"] == "same-task"
    assert left.extra["markdown_values"] == {"fix": "no", "custom": "a"}
    assert right.extra["markdown_values"] == {"fix": "yes", "custom": "b"}


def test_sync_preserves_crlf_and_missing_final_newline(tmp_path: Path) -> None:
    sources = (
        "task | fix:no | esc:0 | worktree:-\r\n",
        "task | fix:no | esc:0 | worktree:-",
    )
    for index, source in enumerate(sources):
        plan = tmp_path / "working" / "plans" / str(index)
        queue = plan / "notes" / "queue.md"
        queue.parent.mkdir(parents=True)
        queue.write_bytes(source.encode())
        import_line_queue(plan)
        assert export_line_queue(plan) == source

from pathlib import Path

import pytest
from varde_data.backends.sqlite.plan_state import SQLitePlanState
from varde_data.errors import Invalid
from varde_data.plan_state_sync import export_plan_dir, import_plan_dir


def _plan_dir(root: Path) -> Path:
    directory = root / "plans" / "example"
    (directory / "tasks").mkdir(parents=True)
    (directory / "plan.md").write_bytes(
        b"---\nstatus: todo\nstatus_at: old\nowner: old-owner\n"
        b"custom_key: keep me\n---\nBody stays byte-identical.\n"
    )
    (directory / "tasks" / "01-work.md").write_bytes(
        b"---\nstatus: todo\nstatus_at: old\nunknown: untouched\n---\nTask body.\n"
    )
    return directory


def test_export_changes_only_state_fields_and_preserves_unknown_frontmatter(
    tmp_path: Path,
) -> None:
    directory = _plan_dir(tmp_path)
    plan_file = directory / "plan.md"
    task_file = directory / "tasks" / "01-work.md"
    plan_before = plan_file.read_bytes()
    task_before = task_file.read_bytes()
    store = SQLitePlanState(tmp_path / ".cache/data/queue.sqlite3")
    store.set_plan_state(
        str(directory), status="building", status_at="new", owner="old-owner"
    )
    store.set_task_state(str(directory), "01-work", "in_review", actor="worker")

    export_plan_dir(store.path.parents[2], directory)

    plan_after = plan_file.read_bytes()
    task_after = task_file.read_bytes()
    assert plan_after == (
        b"---\nstatus: building\nstatus_at: new\nowner: old-owner\n"
        b"custom_key: keep me\n---\nBody stays byte-identical.\n"
    )
    task_state = store.task_states(str(directory))[0]
    assert task_after == (
        f"---\nstatus: in_review\nstatus_at: {task_state.status_at}\n".encode()
        + b"unknown: untouched\n---\nTask body.\n"
    )
    assert b"custom_key: keep me" in plan_after
    assert b"unknown: untouched" in task_after
    assert plan_after.split(b"---\n", 2)[2] == plan_before.split(b"---\n", 2)[2]
    assert task_after.split(b"---\n", 2)[2] == task_before.split(b"---\n", 2)[2]


def test_hand_edited_status_imported_once_with_markdown_source(tmp_path: Path) -> None:
    directory = _plan_dir(tmp_path)
    store = SQLitePlanState(tmp_path / ".cache/data/queue.sqlite3")
    store.set_plan_state(str(directory), status="building", status_at="old")
    store.set_task_state(str(directory), "01-work", "building", actor="worker")
    export_plan_dir(store.path.parents[2], directory)

    task_file = directory / "tasks" / "01-work.md"
    task_file.write_bytes(task_file.read_bytes().replace(b"building", b"done"))
    import_plan_dir(store.path.parents[2], directory)

    assert store.task_states(str(directory))[0].status == "done"
    with store._connection() as db:
        event = db.execute(
            "SELECT * FROM queue_events WHERE source='markdown'"
        ).fetchone()
    assert event["actor"] == "markdown"
    assert event["from_state"] == "building"
    assert event["to_state"] == "done"
    import_plan_dir(store.path.parents[2], directory)
    with store._connection() as db:
        assert (
            db.execute(
                "SELECT count(*) FROM queue_events WHERE source='markdown'"
            ).fetchone()[0]
            == 1
        )


def test_import_empty_store_loads_plan_and_every_task(tmp_path: Path) -> None:
    directory = _plan_dir(tmp_path)
    store = SQLitePlanState(tmp_path / ".cache/data/queue.sqlite3")

    import_plan_dir(store.path.parents[2], directory)

    plan = store.plan_state(str(directory))
    task = store.task_states(str(directory))[0]
    assert plan.status == "todo"
    assert plan.owner == "old-owner"
    assert task.status == "todo"
    with store._connection() as db:
        events = db.execute(
            "SELECT item_id,from_state,to_state,source FROM queue_events ORDER BY seq"
        ).fetchall()
    assert [(row["from_state"], row["to_state"], row["source"]) for row in events] == [
        (None, "todo", "markdown"),
        (None, "todo", "markdown"),
    ]


def test_import_skips_and_reports_task_markdown_without_state_frontmatter(
    tmp_path: Path,
) -> None:
    directory = _plan_dir(tmp_path)
    no_frontmatter = directory / "tasks" / "explorer-brief.md"
    no_frontmatter.write_text("Shared brief for explorers.\n- Read only.\n")
    no_status = directory / "tasks" / "task-1.md"
    no_status.write_text("---\nowner: worker\n---\nTask description.\n")
    store = SQLitePlanState(tmp_path / ".cache/data/queue.sqlite3")

    skipped = import_plan_dir(store.path.parents[2], directory)

    assert skipped == (str(no_frontmatter), str(no_status))
    assert [task.task_id for task in store.task_states(directory)] == ["01-work"]


def test_imports_crlf_task_frontmatter(tmp_path: Path) -> None:
    directory = _plan_dir(tmp_path)
    task = directory / "tasks" / "crlf-task.md"
    task.write_bytes(b"---\r\nstatus: todo\r\n---\r\nTask body.\r\n")
    store = SQLitePlanState(tmp_path / ".cache/data/queue.sqlite3")

    skipped = import_plan_dir(store.path.parents[2], directory)

    assert skipped == ()
    assert {task.task_id: task.status for task in store.task_states(directory)} == {
        "01-work": "todo",
        "crlf-task": "todo",
    }


def test_import_rejects_present_null_task_status(tmp_path: Path) -> None:
    directory = _plan_dir(tmp_path)
    task = directory / "tasks" / "null-status.md"
    task.write_text("---\nstatus: null\n---\nTask body.\n")
    store = SQLitePlanState(tmp_path / ".cache/data/queue.sqlite3")

    with pytest.raises(Invalid, match="task status .* must be a scalar"):
        import_plan_dir(store.path.parents[2], directory)


def test_status_only_update_and_export_keep_plan_metadata(tmp_path: Path) -> None:
    directory = _plan_dir(tmp_path)
    store = SQLitePlanState(tmp_path / ".cache/data/queue.sqlite3")
    store.set_plan_state(
        str(directory),
        status="todo",
        status_at="before",
        owner="old-owner",
        assigned_to="assignee",
        merge_approved_at="approved",
    )
    store.set_plan_state(str(directory), status="building")

    export_plan_dir(store.path.parents[2], directory)

    raw = (directory / "plan.md").read_bytes()
    assert b"owner: old-owner\n" in raw
    assert b"assigned_to: assignee\n" in raw
    assert b"merge_approved_at: approved\n" in raw


def test_unexported_store_state_wins_and_plan_path_is_canonical(tmp_path: Path) -> None:
    directory = _plan_dir(tmp_path)
    store = SQLitePlanState(tmp_path / ".cache/data/queue.sqlite3")
    store.set_plan_state(str(directory), status="building")
    store.set_task_state(str(directory), "01-work", "building", actor="worker")
    (directory / "plan.md").write_bytes(
        (directory / "plan.md").read_bytes().replace(b"status: todo", b"status: done")
    )
    (directory / "tasks" / "01-work.md").write_bytes(
        (directory / "tasks" / "01-work.md")
        .read_bytes()
        .replace(b"status: todo", b"status: done")
    )

    import_plan_dir(store.path.parents[2], directory / "plan.md")

    assert store.plan_state(directory).status == "building"
    assert store.task_states(directory)[0].status == "building"


def test_unexported_update_after_export_wins_over_old_markdown(tmp_path: Path) -> None:
    directory = _plan_dir(tmp_path)
    store = SQLitePlanState(tmp_path / ".cache/data/queue.sqlite3")
    store.set_plan_state(str(directory), status="todo")
    store.set_task_state(str(directory), "01-work", "todo", actor="worker")
    export_plan_dir(store.path.parents[2], directory)
    store.set_plan_state(str(directory), status="building")
    store.set_task_state(str(directory), "01-work", "building", actor="worker")

    import_plan_dir(store.path.parents[2], directory)

    assert store.plan_state(directory).status == "building"
    assert store.task_states(directory)[0].status == "building"


def test_task_events_are_unique_between_plans_and_dates_hash_as_scalars(
    tmp_path: Path,
) -> None:
    first = _plan_dir(tmp_path)
    second = tmp_path / "plans" / "other"
    (second / "tasks").mkdir(parents=True)
    (second / "plan.md").write_text(
        "---\nstatus: todo\nstatus_at: 2026-10-26\n---\n", encoding="utf-8"
    )
    (second / "tasks" / "01-work.md").write_text(
        "---\nstatus: todo\nstatus_at: 2026-10-26\n---\n", encoding="utf-8"
    )
    store = SQLitePlanState(tmp_path / ".cache/data/queue.sqlite3")

    import_plan_dir(store.path.parents[2], first)
    import_plan_dir(store.path.parents[2], second / "plan.md")

    assert store.plan_state(second).status_at == "2026-10-26"
    with store._connection() as db:
        ids = [
            row[0]
            for row in db.execute(
                "SELECT item_id FROM queue_events WHERE item_id LIKE 'task:%'"
            )
        ]
    assert len(ids) == 2
    assert len(set(ids)) == 2

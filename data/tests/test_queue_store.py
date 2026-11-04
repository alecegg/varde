import sqlite3

import pytest
from varde_data.backends.sqlite.messages import SQLiteMessages
from varde_data.errors import NotFound, WrongMode
from varde_data.plan_state import open_plan_state
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import (
    create_backup,
    export_metadata,
    initialize,
    restore_backup,
    status,
)
from varde_data.records.messages import NewMessage


def test_initialize_status_and_export_metadata(tmp_path):
    initialize(tmp_path)
    plan_dir = tmp_path / "plans" / "alpha"
    state = open_plan_state(tmp_path)
    state.set_plan_state(str(plan_dir), status="active", owner="builder")
    state.set_task_state(str(plan_dir), "T1", "in_progress", actor="builder")
    database = tmp_path / QUEUE_DATABASE
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )
        connection.execute(
            "INSERT INTO queue_meta(queue_name) VALUES ('roles/builder')"
        )

    report = status(tmp_path)
    assert report["exists"] is True
    assert report["mode"] == "sqlite"
    assert report["counts"]["plan_state"] == 1
    assert report["counts"]["task_state"] == 1
    assert export_metadata(tmp_path) == (["roles/builder"], [plan_dir.resolve()])


def test_export_metadata_requires_sqlite_mode(tmp_path):
    initialize(tmp_path)

    with pytest.raises(WrongMode, match="not in sqlite mode"):
        export_metadata(tmp_path)


def test_backup_and_restore_preserve_queue_store(tmp_path):
    initialize(tmp_path)
    state = open_plan_state(tmp_path)
    state.set_plan_state(str(tmp_path / "plans" / "before"), status="active")
    backup = create_backup(tmp_path)
    state.set_plan_state(str(tmp_path / "plans" / "after"), status="backlog")

    restored = restore_backup(tmp_path, backup)

    assert restored == tmp_path / QUEUE_DATABASE
    assert status(tmp_path)["counts"]["plan_state"] == 1
    assert state.plan_state(tmp_path / "plans" / "before").status == "active"
    with pytest.raises(NotFound):
        state.plan_state(tmp_path / "plans" / "after")


def test_initialize_targets_merged_database_and_writes_queue_marker(tmp_path):
    initialize(tmp_path)

    database = tmp_path / QUEUE_DATABASE
    assert database.is_file()
    assert (tmp_path / ".cache/data/queue.version").read_text() == "4\n"
    assert open_plan_state(tmp_path) is not None


def test_queue_backup_restore_preserves_current_messages(tmp_path):
    initialize(tmp_path)
    state = open_plan_state(tmp_path)
    state.set_plan_state(str(tmp_path / "plans" / "before"), status="active")
    messages = SQLiteMessages(tmp_path / QUEUE_DATABASE)
    messages.append(NewMessage("main", "role:builder", "info", "kept"))
    backup = create_backup(tmp_path)
    state.set_plan_state(str(tmp_path / "plans" / "after"), status="backlog")
    messages.append(NewMessage("main", "role:builder", "info", "newer mail"))

    restore_backup(tmp_path, backup)

    assert state.plan_state(tmp_path / "plans" / "before").status == "active"
    with pytest.raises(NotFound):
        state.plan_state(tmp_path / "plans" / "after")
    assert [message.text for message in messages.read_all().records] == [
        "kept",
        "newer mail",
    ]

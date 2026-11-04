import sqlite3

from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.backends.sqlite.queue_schema import configure_store
from varde_data.records.queue import QueueItemInput


def test_unwritten_dependency_is_accepted_but_item_is_not_claimable(tmp_path):
    queue = SQLiteQueue(tmp_path / "queue.sqlite3")
    item = queue.enqueue(
        QueueItemInput(
            "dependent",
            "plan",
            queue_name="roles/global",
            depends_on=("future-item",),
        )
    )

    assert item.depends_on == ("future-item",)
    assert queue.claim("roles/global", worker="worker", lease_s=60, role=None) is None


def test_followup_depth_migrates_existing_queue_rows(tmp_path):
    database = tmp_path / "queue.sqlite3"
    with sqlite3.connect(database) as connection:
        configure_store(connection)
        connection.execute(
            "INSERT INTO queue_items "
            "(id, plan_dir, findings, owned_files, state, queue_name) "
            "VALUES ('existing', 'plan', '', '', 'queued', 'roles/global')"
        )
        connection.execute("ALTER TABLE queue_items DROP COLUMN followup_depth")
        connection.execute("PRAGMA user_version = 2")
        connection.commit()

    queue = SQLiteQueue(database)

    assert queue.get("roles/global", "existing").followup_depth == 0


def test_followup_cap_depth_round_trips_through_sqlite(tmp_path):
    queue = SQLiteQueue(tmp_path / "queue.sqlite3")

    item = queue.enqueue(
        QueueItemInput("child", "plan", followup_depth=2, queue_name="roles/global")
    )

    assert item.followup_depth == 2

import sqlite3

import pytest
from varde_data.backends.sqlite.queue_schema import SCHEMA_VERSION, configure_store
from varde_data.errors import Invalid


def test_fresh_create_and_idempotent_reopen(tmp_path):
    path = tmp_path / "queue.sqlite3"
    with sqlite3.connect(path) as connection:
        configure_store(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "queue_items",
            "queue_events",
            "plan_state",
            "task_state",
            "queue_meta",
            "meta",
            "slots",
            "slot_events",
        } <= tables
        assert _columns(connection, "queue_items") == {
            "id",
            "plan_dir",
            "findings",
            "owned_files",
            "depends_cell",
            "depends_on",
            "serialize_with",
            "priority",
            "state",
            "planned_at",
            "plan_reviewed_at",
            "build_started_at",
            "build_done_at",
            "merged_at",
            "role",
            "claimed_by",
            "claim_expires_at",
            "claim_generation",
            "claim_epoch",
            "queue_name",
            "row_order",
            "extra",
            "followup_depth",
        }
        configure_store(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_upgrade_v1_keeps_queue_rows_and_adds_slots(tmp_path):
    path = tmp_path / "queue.sqlite3"
    with sqlite3.connect(path) as connection:
        configure_store(connection)
        connection.execute(
            "INSERT INTO queue_items "
            "(id, plan_dir, findings, owned_files, state, queue_name) "
            "VALUES ('one', 'plan', '', '', 'queued', 'build')"
        )
        connection.execute("DROP TABLE IF EXISTS slot_events")
        connection.execute("DROP TABLE IF EXISTS slots")
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
        configure_store(connection)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT id FROM queue_items").fetchall() == [("one",)]
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"slots", "slot_events"} <= tables


def test_refuses_newer_version_without_modifying_database(tmp_path):
    path = tmp_path / "queue.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    before = path.read_bytes()
    with sqlite3.connect(path) as connection, pytest.raises(Invalid, match="newer"):
        configure_store(connection)
    assert path.read_bytes() == before


def _columns(connection, table):
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}

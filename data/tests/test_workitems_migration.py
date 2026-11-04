from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
import varde_data.backends.sqlite.workitems as sqlite_workitems
from varde_data.backends.sqlite.workitems import SqliteWorkItems
from varde_data.errors import Invalid

FIXTURES = Path(__file__).parent / "fixtures" / "workitems"


@pytest.mark.parametrize(
    "fixture", sorted(FIXTURES.glob("v0_*.sqlite3")), ids=lambda p: p.name
)
def test_migrates_legacy_workitem_databases(tmp_path: Path, fixture: Path) -> None:
    shutil.copy2(fixture, tmp_path / "workitems.sqlite3")
    before = _rows(tmp_path / "workitems.sqlite3")
    with sqlite3.connect(tmp_path / "workitems.sqlite3") as db:
        old_item_columns = {
            row[1] for row in db.execute("PRAGMA table_info(work_items)")
        }
        old_question_columns = {
            row[1] for row in db.execute("PRAGMA table_info(work_item_questions)")
        }

    SqliteWorkItems(tmp_path)
    after = _rows(tmp_path / "workitems.sqlite3")
    for old_table, new_table in zip(before, after, strict=True):
        assert [row[: len(old_table[0])] for row in new_table] == old_table
    with sqlite3.connect(tmp_path / "workitems.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        item_columns = {row[1] for row in db.execute("PRAGMA table_info(work_items)")}
        question_columns = {
            row[1] for row in db.execute("PRAGMA table_info(work_item_questions)")
        }
        assert {"launch_request_id", "launch_request_notes"} <= item_columns
        assert "answer_key" in question_columns
        null_checks = {
            "launch_request_id": "SELECT count(*) FROM work_items "
            "WHERE launch_request_id IS NOT NULL",
            "launch_request_notes": "SELECT count(*) FROM work_items "
            "WHERE launch_request_notes IS NOT NULL",
        }
        for column, query in null_checks.items():
            if column not in old_item_columns:
                assert db.execute(query).fetchone()[0] == 0
        if "answer_key" not in old_question_columns:
            assert (
                db.execute(
                    "SELECT count(*) FROM work_item_questions "
                    "WHERE answer_key IS NOT NULL"
                ).fetchone()[0]
                == 0
            )
        assert db.execute("SELECT count(*) FROM meta").fetchone()[0] == 1
        if fixture.name == "v0_current_wal.sqlite3":
            assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"

    SqliteWorkItems(tmp_path)
    with sqlite3.connect(tmp_path / "workitems.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT version FROM meta").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM work_items").fetchone()[0] == len(
            before[0]
        )


def test_refuses_newer_schema(tmp_path: Path) -> None:
    SqliteWorkItems(tmp_path)
    with sqlite3.connect(tmp_path / "workitems.sqlite3") as db:
        db.execute("PRAGMA user_version = 2")
    with pytest.raises(Invalid, match="newer"):
        SqliteWorkItems(tmp_path)


def test_failed_migration_rolls_back_all_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = FIXTURES / "v0_oldest.sqlite3"
    shutil.copy2(fixture, tmp_path / "workitems.sqlite3")
    before = _schema_and_rows(tmp_path / "workitems.sqlite3")
    configure = sqlite_workitems.configure_connection

    def fail_meta_creation(db: sqlite3.Connection) -> None:
        configure(db)

        def deny_meta(action: int, table: str | None, *_: object) -> int:
            if action == sqlite3.SQLITE_CREATE_TABLE and table == "meta":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        db.set_authorizer(deny_meta)

    monkeypatch.setattr(sqlite_workitems, "configure_connection", fail_meta_creation)
    with pytest.raises(sqlite3.DatabaseError):
        SqliteWorkItems(tmp_path)

    assert _schema_and_rows(tmp_path / "workitems.sqlite3") == before
    with sqlite3.connect(tmp_path / "workitems.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0


def _rows(path: Path) -> tuple[list[tuple[object, ...]], ...]:
    with sqlite3.connect(path) as db:
        items = db.execute("SELECT * FROM work_items ORDER BY id").fetchall()
        questions = db.execute(
            "SELECT * FROM work_item_questions ORDER BY item_id,msg_id"
        ).fetchall()
        audit = db.execute("SELECT * FROM work_item_audit ORDER BY seq").fetchall()
    return items, questions, audit


def _schema_and_rows(path: Path) -> tuple[object, ...]:
    with sqlite3.connect(path) as db:
        schema = db.execute(
            "SELECT type,name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
        return schema, _rows(path), db.execute("PRAGMA user_version").fetchone()[0]

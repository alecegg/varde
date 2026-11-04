from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.backends.sqlite.queue_backup import backup, restore
from varde_data.backends.sqlite.queue_schema import SCHEMA_VERSION
from varde_data.errors import Invalid
from varde_data.queue_sync import export_queue_md, import_queue_md

_FIXTURE = Path(__file__).parent / "fixtures" / "queue_md" / "ux-audit-fixes-1.md"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _database_family(path: Path) -> dict[Path, str]:
    return {
        candidate: _sha256(candidate)
        for candidate in (path, Path(f"{path}-wal"))
        if candidate.exists()
    }


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        (b"", "empty"),
        (b"SQLite format 3\x00" + b"x" * 80, "malformed|database|corrupt"),
        (b"not a sqlite database", "not a database"),
    ],
    ids=("zero-length", "truncated", "random-bytes"),
)
def test_corrupt_database_is_rejected_without_changes(
    tmp_path: Path, contents: bytes, message: str
) -> None:
    path = tmp_path / "queue.sqlite3"
    path.write_bytes(contents)
    before = _database_family(path)

    with pytest.raises(Invalid, match=message) as error:
        SQLiteQueue(path)

    assert _database_family(path) == before
    assert "varde plan store restore" in str(error.value)
    assert "varde plan store import" in str(error.value)


@pytest.mark.parametrize("wal_damage", ["deleted", "truncated"])
def test_damaged_wal_is_rejected_without_changes(
    tmp_path: Path, wal_damage: str
) -> None:
    path = tmp_path / "queue.sqlite3"
    wal = Path(f"{path}-wal")
    keeper = sqlite3.connect(path)
    keeper.execute("PRAGMA journal_mode=WAL")
    keeper.execute("PRAGMA wal_autocheckpoint=0")
    with keeper:
        keeper.execute(
            "CREATE TABLE wal_content(value TEXT NOT NULL CHECK(length(value) > 0))"
        )
        keeper.execute("INSERT INTO wal_content VALUES ('uncheckpointed')")
    assert wal.exists()
    if wal_damage == "deleted":
        wal.unlink()
    else:
        wal.write_bytes(wal.read_bytes()[:24])
    before = _database_family(path)

    try:
        with pytest.raises(Invalid) as error:
            SQLiteQueue(path)
        assert _database_family(path) == before
    finally:
        keeper.close()

    assert "varde plan store restore" in str(error.value)
    assert "varde plan store import" in str(error.value)


def test_newer_schema_is_rejected_without_changes(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    SQLiteQueue(path)
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    before = _sha256(path)

    with pytest.raises(Invalid, match="newer") as error:
        SQLiteQueue(path)

    assert _sha256(path) == before
    assert "varde plan store restore" in str(error.value)
    assert "varde plan store import" in str(error.value)


def test_failed_integrity_check_is_rejected_without_changes(tmp_path: Path) -> None:
    path = tmp_path / "queue.sqlite3"
    SQLiteQueue(path)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("CREATE TABLE damaged(value TEXT NOT NULL)")
        db.executemany("INSERT INTO damaged VALUES (?)", [("x" * 2000,)] * 40)
        page_size = db.execute("PRAGMA page_size").fetchone()[0]
        root_page = db.execute(
            "SELECT rootpage FROM sqlite_master WHERE name='damaged'"
        ).fetchone()[0]
    payload = bytearray(path.read_bytes())
    payload[(root_page - 1) * page_size + 40] ^= 0xFF
    path.write_bytes(payload)
    before = _database_family(path)

    with pytest.raises(Invalid, match="integrity") as error:
        SQLiteQueue(path)

    assert _database_family(path) == before
    assert "varde plan store restore" in str(error.value)
    assert "varde plan store import" in str(error.value)


def test_backup_restore_recovers_all_queue_rows(tmp_path: Path) -> None:
    working = tmp_path / "working"
    queue_path = working / "plans" / "bundle" / "queue.md"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    report = import_queue_md(queue_path, "bundle")
    assert report.added == 6
    expected = SQLiteQueue(working / ".cache/data/queue.sqlite3").list("bundle")
    snapshot = backup(working)

    database = working / ".cache/data/queue.sqlite3"
    database.unlink()
    restore(working, snapshot)

    assert SQLiteQueue(database).list("bundle") == expected


def test_markdown_export_rebuild_recovers_all_queue_rows(tmp_path: Path) -> None:
    working = tmp_path / "working"
    queue_path = working / "plans" / "bundle" / "queue.md"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    assert import_queue_md(queue_path, "bundle").added == 6
    expected = SQLiteQueue(working / ".cache/data/queue.sqlite3").list("bundle")
    markdown_export = export_queue_md(working, "bundle")
    database = working / ".cache/data/queue.sqlite3"
    database.unlink()

    queue_path.write_text(markdown_export, encoding="utf-8")
    assert import_queue_md(queue_path, "bundle").added == 6

    assert SQLiteQueue(database).list("bundle") == expected

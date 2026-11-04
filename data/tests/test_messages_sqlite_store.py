from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from varde_data.backends.sqlite.messages import SCHEMA_VERSION, SQLiteMessages, factory
from varde_data.errors import Invalid, Locked
from varde_data.messages import message_store_files, messages_db_path, open_messages
from varde_data.records.messages import Delivery, Message, NewMessage
from varde_data.store_mode import (
    _mark_import_verified,
    marker_path,
    read_store_mode,
    set_store_mode,
)
from varde_data.version import Cursor


def test_sqlite_store_path_and_connection_settings(tmp_path: Path) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    set_store_mode(working, "mirror-sqlite")
    set_store_mode(working, "sqlite")
    repository = open_messages(working, "sqlite")
    assert isinstance(repository, SQLiteMessages)
    path = messages_db_path(working)
    assert path == working / ".cache" / "inbox" / "messages.sqlite3"
    assert message_store_files(working) == (
        path,
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
    )

    seen_synchronous: list[int] = []
    connect = repository._connect

    def observe_connection() -> sqlite3.Connection:
        db = connect()
        seen_synchronous.append(db.execute("PRAGMA synchronous").fetchone()[0])
        return db

    repository._connect = observe_connection
    assert repository.head().value == "0"
    repository.register_reader("reader", from_start=True)
    assert repository.peek_unread("reader") == ()
    assert repository.claim_unread("reader", "s", "hook") == ()
    repository.append(NewMessage("sender", "reader", "info", "body", ts="t"))
    assert repository.claim_unread("reader", "s", "hook", "t")
    assert len(seen_synchronous) >= 5
    assert set(seen_synchronous) == {2}

    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_newer_user_version_is_rejected(tmp_path: Path) -> None:
    path = messages_db_path(tmp_path / "working")
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")

    with pytest.raises(Invalid, match="newer than supported"):
        factory(tmp_path / "working")


@pytest.mark.parametrize("version", (3, 4))
def test_legacy_migration_preserves_reader_cursor_and_creates_holder_cursor(
    tmp_path: Path, version: int
) -> None:
    working = tmp_path / "working"
    path = messages_db_path(working)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE messages(id TEXT,legacy_id TEXT,ts TEXT NOT NULL,"
            "sender TEXT NOT NULL,recipient TEXT NOT NULL,kind TEXT NOT NULL,"
            "body TEXT NOT NULL,notes TEXT,reply_to TEXT,seq INTEGER PRIMARY KEY);"
            "CREATE TABLE readers(reader TEXT PRIMARY KEY,cursor INTEGER NOT NULL);"
            "CREATE TABLE cursor_positions(reader TEXT PRIMARY KEY,position INTEGER);"
            "CREATE TABLE deliveries(seq INTEGER PRIMARY KEY,message_id TEXT,"
            "reader TEXT,session TEXT,via TEXT,event TEXT,at TEXT,"
            "action_created_at TEXT,reason TEXT,details TEXT);"
            "CREATE TABLE meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL);"
            "INSERT INTO messages VALUES('m-00000001',NULL,'t','sender',"
            "'team:alpha','info','body',NULL,NULL,1);"
            "INSERT INTO readers VALUES('team:alpha',0);"
            "INSERT INTO cursor_positions VALUES('team:alpha',0);"
        )
        db.execute(f"PRAGMA user_version={version}")

    migrated = factory(working)

    assert [message.id for message in migrated.peek_unread("team:alpha")] == [
        "m-00000001"
    ]
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT role_key,holder,cursor_seq FROM role_holder_cursors"
        ).fetchall() == [("team:alpha", "team:alpha", 0)]
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
    backups = tuple((path.parent / "backups").glob("messages-v4-*.sqlite3"))
    assert len(backups) == (1 if version == 4 else 0)
    if version == 4:
        with sqlite3.connect(backups[0]) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 4


def test_failed_migration_restores_store_marker_and_database_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    set_store_mode(working, "mirror-sqlite")
    expected = set_store_mode(working, "sqlite")
    path = messages_db_path(working)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=4")
    marker = marker_path(working)
    marker_payload = marker.read_bytes()
    original = SQLiteMessages._apply_migration

    def corrupt_then_fail(repository, db):
        original(repository, db)
        db.execute("UPDATE meta SET value='corrupt' WHERE key='store_mode'")
        db.commit()
        marker.write_text("corrupt", encoding="utf-8")
        raise Invalid("forced migration failure")

    monkeypatch.setattr(SQLiteMessages, "_apply_migration", corrupt_then_fail)
    with pytest.raises(Invalid, match="forced migration failure"):
        factory(working)

    assert marker.read_bytes() == marker_payload
    assert read_store_mode(working) == expected
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert (
            db.execute("SELECT value FROM meta WHERE key='store_mode'").fetchone()[0]
            == expected.to_json()
        )


def test_migration_rejects_a_missing_seeded_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "working"
    path = messages_db_path(working)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE messages(id TEXT,legacy_id TEXT,ts TEXT NOT NULL,"
            "sender TEXT NOT NULL,recipient TEXT NOT NULL,kind TEXT NOT NULL,"
            "body TEXT NOT NULL,notes TEXT,reply_to TEXT,seq INTEGER PRIMARY KEY);"
            "CREATE TABLE readers(reader TEXT PRIMARY KEY,cursor INTEGER NOT NULL);"
            "CREATE TABLE cursor_positions(reader TEXT PRIMARY KEY,position INTEGER);"
            "CREATE TABLE deliveries(seq INTEGER PRIMARY KEY,message_id TEXT,"
            "reader TEXT,session TEXT,via TEXT,event TEXT,at TEXT,"
            "action_created_at TEXT,reason TEXT,details TEXT);"
            "CREATE TABLE meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL);"
            "INSERT INTO messages VALUES('m-00000001',NULL,'t','sender',"
            "'team','info','body',NULL,NULL,1);"
            "INSERT INTO readers VALUES('team',0);"
            "PRAGMA user_version=4;"
        )
    monkeypatch.setattr(
        SQLiteMessages,
        "_seed_role_holder_cursors",
        lambda _repository, _db: None,
        raising=False,
    )

    with pytest.raises(Invalid, match="unread set"):
        factory(working)

    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4


def test_schema_version_is_pinned() -> None:
    assert SCHEMA_VERSION == 5


def test_role_inbox_keeps_holder_cursors_independent(tmp_path: Path) -> None:
    from varde_data.role_inbox import open_role_inbox

    inbox = open_role_inbox(tmp_path / "working")
    inbox.add_holder("team:alpha", "slot-a")
    inbox.add_holder("team:alpha", "slot-b")
    message = inbox.append(
        "team:alpha", NewMessage("sender", "unused", "info", "shared", ts="t")
    )

    assert [row.id for row in inbox.unread("team:alpha", "slot-a")] == [message.id]
    assert [row.id for row in inbox.unread("team:alpha", "slot-b")] == [message.id]
    with sqlite3.connect(messages_db_path(tmp_path / "working")) as db:
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1

    inbox.advance("team:alpha", "slot-a", 1)
    assert inbox.unread("team:alpha", "slot-a") == ()
    assert len(inbox.unread("team:alpha", "slot-b")) == 1
    inbox.ack("team:alpha", "slot-b", message.id or "")
    assert inbox.unread("team:alpha", "slot-b") == ()


def test_successor_inherits_predecessor_cursor(tmp_path: Path) -> None:
    from varde_data.role_inbox import open_role_inbox

    inbox = open_role_inbox(tmp_path / "working")
    inbox.add_holder("team:alpha", "slot-old")
    earlier = inbox.append(
        "team:alpha", NewMessage("sender", "team:alpha", "info", "read", ts="t")
    )
    pending = inbox.append(
        "team:alpha", NewMessage("sender", "team:alpha", "info", "pending", ts="t")
    )
    inbox.advance("team:alpha", "slot-old", 1)

    inbox.add_holder("team:alpha", "slot-new", inherit_from="slot-old")

    assert earlier.id != pending.id
    assert [row.id for row in inbox.unread("team:alpha", "slot-new")] == [pending.id]


def test_first_holder_receives_mail_queued_before_binding(tmp_path: Path) -> None:
    from varde_data.role_inbox import open_role_inbox

    inbox = open_role_inbox(tmp_path / "working")
    old = inbox.append(
        "team:alpha", NewMessage("sender", "team:alpha", "info", "old", ts="t")
    )
    queued = inbox.append(
        "team:alpha", NewMessage("sender", "team:alpha", "info", "queued", ts="t")
    )
    inbox.add_holder("team:alpha", "slot-new")

    assert [row.id for row in inbox.unread("team:alpha", "slot-new")] == [
        old.id,
        queued.id,
    ]


def test_later_holder_starts_at_role_head(tmp_path: Path) -> None:
    from varde_data.role_inbox import open_role_inbox

    inbox = open_role_inbox(tmp_path / "working")
    inbox.add_holder("team:alpha", "slot-first")
    inbox.append(
        "team:alpha", NewMessage("sender", "team:alpha", "info", "old", ts="t")
    )

    inbox.add_holder("team:alpha", "slot-later")

    assert inbox.unread("team:alpha", "slot-later") == ()


def test_first_live_holder_inherits_lowest_stale_cursor(tmp_path: Path) -> None:
    from varde_data.role_inbox import open_role_inbox

    inbox = open_role_inbox(tmp_path / "working")
    inbox.add_holders("team:alpha", ("slot-old-a", "slot-old-b"))
    rows = [
        inbox.append(
            "team:alpha",
            NewMessage("sender", "team:alpha", "info", f"mail {index}", ts="t"),
        )
        for index in range(3)
    ]
    inbox.advance("team:alpha", "slot-old-a", 2)
    inbox.advance("team:alpha", "slot-old-b", 1)

    inbox.add_holders("team:alpha", ("slot-new",), live_holders=("slot-new",))

    assert [row.id for row in inbox.unread("team:alpha", "slot-new")] == [
        rows[1].id,
        rows[2].id,
    ]


def test_add_existing_holder_does_not_start_write_transaction(
    tmp_path: Path, monkeypatch
) -> None:
    from contextlib import contextmanager

    from varde_data.role_inbox import open_role_inbox

    inbox = open_role_inbox(tmp_path / "working")
    inbox.add_holder("team:alpha", "slot-a")
    statements: list[str] = []
    connection = inbox._repository._connection

    @contextmanager
    def trace_connection():
        with connection() as db:
            db.set_trace_callback(statements.append)
            yield db

    monkeypatch.setattr(inbox._repository, "_connection", trace_connection)
    inbox.add_holder("team:alpha", "slot-a")

    assert not any("BEGIN IMMEDIATE" in statement for statement in statements)


def test_role_inbox_selection_tracks_active_store_mode(tmp_path: Path) -> None:
    from varde_data.role_inbox import select_role_inbox
    from varde_data.store_mode import _mark_import_verified, set_store_mode

    assert select_role_inbox(tmp_path) is None
    _mark_import_verified(tmp_path, verified_at="2026-10-28T00:00:00Z")
    set_store_mode(tmp_path, "mirror-files")
    set_store_mode(tmp_path, "mirror-sqlite")
    set_store_mode(tmp_path, "sqlite")

    assert select_role_inbox(tmp_path) is not None


@pytest.mark.parametrize("event", ("delivered", "acked"))
def test_role_unread_honors_delivery_events(tmp_path: Path, event: str) -> None:
    from varde_data.role_inbox import open_role_inbox

    working = tmp_path / "working"
    inbox = open_role_inbox(working)
    inbox.add_holder("team:alpha", "slot-a")
    message = inbox.append(
        "team:alpha", NewMessage("sender", "team:alpha", "info", "delivered", ts="t")
    )
    with sqlite3.connect(messages_db_path(working)) as db:
        db.execute(
            "INSERT INTO deliveries(message_id,reader,session,via,event,at) "
            "VALUES(?,?,'session','hook',?,'t')",
            (message.id, "slot-a", event),
        )

    assert inbox.unread("team:alpha", "slot-a") == ()


def test_migration_adds_missing_schema_without_resetting_meta(tmp_path: Path) -> None:
    working = tmp_path / "working"
    path = messages_db_path(working)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
        db.execute("INSERT INTO meta VALUES ('version', 5)")
        db.commit()

    factory(working)

    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert (
            db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0] == 5
        )
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='cursor_positions'"
        ).fetchone() == ("cursor_positions",)


def test_v2_migration_adds_claim_lookup_index(tmp_path: Path) -> None:
    working = tmp_path / "working"
    path = messages_db_path(working)
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=2")

    factory(working)

    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='deliveries_reader_message_event'"
        ).fetchone() == ("deliveries_reader_message_event",)


def test_claim_candidate_plan_uses_delivery_lookup_index(tmp_path: Path) -> None:
    repository = factory(tmp_path / "working")
    with repository._connection() as db:
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT m.* FROM messages AS m WHERE m.seq>? "
            "AND m.recipient IN (?) AND NOT EXISTS (SELECT 1 FROM deliveries AS d "
            "WHERE d.reader IN (?) AND d.message_id=m.id "
            "AND d.event IN ('delivered','dropped','legacy')) ORDER BY m.seq",
            (0, "reader", "reader"),
        ).fetchall()

    assert any("deliveries_reader_message_event" in row[3] for row in plan)


def test_from_start_reader_skips_contiguous_delivered_history(tmp_path: Path) -> None:
    repository = factory(tmp_path / "working")
    messages = tuple(
        Message("t", "sender", "reader", "info", str(index), id=f"m-{index:08}")
        for index in range(5)
    )
    repository.import_messages(messages)
    repository.import_deliveries(
        tuple(
            Delivery(message.id or "", "reader", "old", "hook", "delivered", "t")
            for message in messages[:4]
        )
    )

    repository.register_reader("reader", from_start=True)

    with repository._connection() as db:
        cursor = db.execute(
            "SELECT cursor FROM readers WHERE reader='reader'"
        ).fetchone()[0]
    assert cursor == 4
    assert repository.claim_unread("reader", "session", "hook") == (messages[4],)


def test_matching_schema_version_skips_migration_writes(tmp_path: Path) -> None:
    repository = factory(tmp_path / "working")
    statements: list[str] = []
    with repository._connection() as db:
        db.set_trace_callback(statements.append)
        repository._migrate(db)

    normalized = [statement.lstrip().upper() for statement in statements]
    assert not any(
        statement.startswith(("CREATE", "ALTER", "DROP", "INSERT", "BEGIN"))
        for statement in normalized
    )


def test_empty_reads_and_claim_do_not_write(tmp_path: Path) -> None:
    repository = factory(tmp_path / "working")
    repository.register_reader("empty-reader", from_start=True)
    db = sqlite3.connect(repository.path)
    before_data_version = db.execute("PRAGMA data_version").fetchone()[0]
    wal = Path(f"{repository.path}-wal")
    before_wal_size = wal.stat().st_size if wal.exists() else 0

    assert repository.peek_unread("empty-reader") == ()
    assert repository.unread("empty-reader") == ()
    assert repository.claim_unread("empty-reader", "s", "hook") == ()
    repository.status()

    assert db.execute("PRAGMA data_version").fetchone()[0] == before_data_version
    assert (wal.stat().st_size if wal.exists() else 0) == before_wal_size
    db.close()


def test_empty_claim_does_not_wait_for_sqlite_writer(tmp_path: Path) -> None:
    repository = factory(tmp_path / "working", busy_timeout=0.15)
    repository.register_reader("empty-reader", from_start=True)
    blocker = sqlite3.connect(repository.path, timeout=0)
    blocker.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    try:
        assert repository.claim_unread("empty-reader", "s", "hook") == ()
    finally:
        blocker.rollback()
        blocker.close()
    assert time.monotonic() - started < 0.1


def test_empty_pending_claim_does_not_wait_for_sqlite_writer(tmp_path: Path) -> None:
    repository = factory(tmp_path / "working", busy_timeout=0.15)
    repository.register_reader("empty-reader", from_start=True)
    blocker = sqlite3.connect(repository.path, timeout=0)
    blocker.execute("BEGIN IMMEDIATE")
    pending_calls: list[bool] = []
    started = time.monotonic()
    try:
        assert (
            repository.claim_unread_with_pending(
                "empty-reader",
                "s",
                "hook",
                None,
                lambda _db: pending_calls.append(True),
            )
            == ()
        )
    finally:
        blocker.rollback()
        blocker.close()
    assert time.monotonic() - started < 0.1
    assert pending_calls == []


def test_busy_timeout_maps_to_locked_for_write_and_claim(tmp_path: Path) -> None:
    working = tmp_path / "working"
    repository = factory(working, busy_timeout=0.15)
    repository.append(NewMessage("sender", "reader", "info", "claim me", ts="t"))
    script = """
import sqlite3
import sys
import time
connection = sqlite3.connect(sys.argv[1])
connection.execute('BEGIN IMMEDIATE')
print('locked', flush=True)
time.sleep(3)
"""
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", script, str(repository.path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "locked"
        for operation in (
            lambda: repository.append(
                NewMessage("sender", "other", "info", "blocked", ts="t")
            ),
            lambda: repository.claim_unread("reader", "s", "hook", "t"),
        ):
            started = time.monotonic()
            with pytest.raises(Locked):
                operation()
            assert time.monotonic() - started < 0.8
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_commit_cursor_does_not_move_delivery_watermark(tmp_path: Path) -> None:
    repository = factory(tmp_path / "working")
    message = repository.append(
        NewMessage("sender", "reader", "info", "unread", ts="t")
    )
    head = repository.head()
    repository.commit_cursor("reader", head)
    with sqlite3.connect(repository.path) as db:
        committed = db.execute(
            "SELECT position FROM cursor_positions WHERE reader='reader'"
        ).fetchone()[0]
    assert committed == int(head.value)
    assert repository.unread("reader") == (message,)
    repository.commit_cursor("reader", Cursor("0"))
    with sqlite3.connect(repository.path) as db:
        assert (
            db.execute(
                "SELECT position FROM cursor_positions WHERE reader='reader'"
            ).fetchone()[0]
            == committed
        )
    assert repository.unread("reader") == (message,)


def test_concluded_addresses_include_file_sources_read_only(tmp_path: Path) -> None:
    working = tmp_path / "working"
    repository = factory(working)
    inbox = working / ".cache" / "inbox"
    (inbox / "state.json").write_text(
        '{"concluded_addresses":["state-only"]}', encoding="utf-8"
    )
    relay_dir = inbox / "relay"
    relay_dir.mkdir()
    (relay_dir / "state.json").write_text(
        '{"concluded_addresses":["relay-only"]}', encoding="utf-8"
    )
    (inbox / "state.json").chmod(0o444)
    (relay_dir / "state.json").chmod(0o444)
    repository.mark_concluded("sqlite-only")
    before = repository.version()

    assert repository.concluded_addresses() == {
        "state-only",
        "relay-only",
        "sqlite-only",
    }
    assert repository.version() == before


def test_message_event_index_is_used(tmp_path: Path) -> None:
    repository = factory(tmp_path / "working")
    with repository._connection() as db:
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM deliveries "
            "WHERE message_id=? AND event='delivered'",
            ("m-00000001",),
        ).fetchall()

    assert any("deliveries_message_event" in row["detail"] for row in plan)


def test_reader_event_index_is_used(tmp_path: Path) -> None:
    repository = factory(tmp_path / "working")
    with repository._connection() as db:
        plan = db.execute(
            "EXPLAIN QUERY PLAN SELECT message_id FROM deliveries "
            "WHERE reader=? AND event=?",
            ("reader", "delivered"),
        ).fetchall()

    assert any("deliveries_reader_event_message" in row["detail"] for row in plan)


def test_read_only_cache_without_inbox_reports_sandbox_hint(tmp_path: Path) -> None:
    working = tmp_path / "working"
    cache = working / ".cache"
    cache.mkdir(parents=True)
    cache.chmod(0o555)
    script = """
from pathlib import Path
import sys
from varde_data.backends.sqlite.messages import factory
from varde_data.errors import Invalid
try:
    factory(Path(sys.argv[1]))
except Invalid as error:
    print(str(error))
else:
    raise SystemExit('expected Invalid')
"""
    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", script, str(working)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    finally:
        cache.chmod(0o755)

    assert result.returncode == 0, result.stderr
    assert "grant write access to .cache/inbox" in result.stdout


def test_read_only_inbox_without_shared_memory_reports_sandbox_hint(
    tmp_path: Path,
) -> None:
    working = tmp_path / "working"
    factory(working)
    inbox = working / ".cache" / "inbox"
    inbox.chmod(0o555)
    script = """
from pathlib import Path
import sys
from varde_data.backends.sqlite.messages import factory
from varde_data.errors import Invalid
try:
    factory(Path(sys.argv[1]))
except Invalid as error:
    print(str(error))
else:
    raise SystemExit('expected Invalid')
"""
    try:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-c", script, str(working)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    finally:
        inbox.chmod(0o755)

    assert result.returncode == 0, result.stderr
    assert "grant write access to .cache/inbox" in result.stdout

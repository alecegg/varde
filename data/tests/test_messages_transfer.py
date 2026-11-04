import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from varde_data.backends.files.messages import FilesMessages
from varde_data.backends.files.slots_reader import SlotReader
from varde_data.backends.sqlite.messages import SQLiteMessages, messages_db_path
from varde_data.errors import Invalid
from varde_data.messages_transfer import export, repair_mode, transfer, verify
from varde_data.records.messages import Delivery, NewMessage
from varde_data.repos.messages import parse_messages
from varde_data.store_mode import (
    StoreModeRecord,
    _mark_import_verified,
    marker_path,
    set_store_mode,
)


def _files(working: Path) -> FilesMessages:
    return FilesMessages.from_store_mode(working, SlotReader(working), None)


def _write_slot_alias(working: Path) -> None:
    slots = working / ".cache" / "inbox" / "slots"
    slots.mkdir(parents=True, exist_ok=True)
    (slots / "slot-a.json").write_text(
        json.dumps({"slot": "slot-a", "aliases": ["alias-a"]}), encoding="utf-8"
    )


def _snapshot_files(working: Path) -> dict[Path, tuple[bytes, int]]:
    inbox = working / ".cache" / "inbox"
    result = {}
    for path in inbox.rglob("*"):
        if path.is_file() and path.name not in {
            "store-mode.lock",
            "store-mode.json",
            "messages.sqlite3",
        }:
            if path.name.endswith(("-wal", "-shm")):
                continue
            result[path] = (path.read_bytes(), path.stat().st_mtime_ns)
    return result


def test_import_copies_legacy_rows_and_skips_invalid_and_torn_tail(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    legacy = {
        "ts": "2026-01-01T00:00:00Z",
        "from": "sender",
        "to": "reader",
        "kind": "info",
        "text": "legacy",
    }
    path = inbox / "messages.jsonl"
    path.write_text(json.dumps(legacy) + '\nnot-json\n{"torn":', encoding="utf-8")
    before_bytes, before_mtime = path.read_bytes(), path.stat().st_mtime_ns

    report = transfer(tmp_path, "files", "sqlite", importing=True)

    assert report.ok
    assert report.skipped == 2
    assert report.torn_tail == 1
    imported = SQLiteMessages(messages_db_path(tmp_path)).read_all().records
    assert len(imported) == 1
    assert imported[0].id == imported[0].legacy_id
    assert path.read_bytes() == before_bytes
    assert path.stat().st_mtime_ns == before_mtime


def test_sqlite_backend_uses_slot_aliases_for_unread(tmp_path: Path) -> None:
    from varde_data.messages import open_messages

    _write_slot_alias(tmp_path)
    source = _files(tmp_path)
    message = source.append(NewMessage("sender", "alias-a", "info", "slot mail"))
    assert transfer(tmp_path, "files", "sqlite", importing=True).ok
    _mark_import_verified(tmp_path, verified_at="2026-01-01T00:00:00+00:00")
    set_store_mode(tmp_path, "mirror-files")
    set_store_mode(tmp_path, "mirror-sqlite")
    set_store_mode(tmp_path, "sqlite")

    repository = open_messages(tmp_path, "sqlite")

    assert [row.id for row in repository.peek_unread("slot-a")] == [message.id]


def test_file_mirror_import_does_not_duplicate_legacy_rows(tmp_path: Path) -> None:
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    path = inbox / "messages.jsonl"
    path.write_text(
        json.dumps(
            {
                "ts": "2026-01-01T00:00:00Z",
                "from": "sender",
                "to": "reader",
                "kind": "info",
                "text": "legacy",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    source = _files(tmp_path)
    legacy = source.read_all().records[0]
    before = path.read_bytes()

    assert source.import_messages((legacy,)) == ()
    assert path.read_bytes() == before


def test_file_unread_legacy_id_keeps_absolute_message_offset(tmp_path: Path) -> None:
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    lines = [
        json.dumps(
            {
                "ts": "2026-01-01T00:00:00Z",
                "from": "sender",
                "to": "other",
                "kind": "info",
                "text": "before cursor",
            }
        ).encode()
        + b"\n",
        json.dumps(
            {
                "ts": "2026-01-01T00:00:01Z",
                "from": "sender",
                "to": "reader",
                "kind": "info",
                "text": "unread legacy",
            }
        ).encode()
        + b"\n",
    ]
    path = inbox / "messages.jsonl"
    path.write_bytes(b"".join(lines))
    (inbox / "index").mkdir()
    (inbox / "index" / "reader.json").write_text(
        json.dumps({"watermark": len(lines[0])}), encoding="utf-8"
    )

    unread = _files(tmp_path).peek_unread("reader")
    expected = parse_messages(path.read_bytes()).records[1]

    assert len(unread) == 1
    assert unread[0].id == expected.id


def test_import_preserves_alias_ack_delivery_history_and_concluded_union(
    tmp_path: Path,
) -> None:
    _write_slot_alias(tmp_path)
    source = _files(tmp_path)
    message = source.append(NewMessage("sender", "slot-a", "info", "ack me"))
    source.claim_unread("alias-a", "session", "test")
    assert source.ack("alias-a", message.id or "")
    source.import_deliveries(
        (
            Delivery(
                message.id or "",
                "slot-a",
                "s",
                "test",
                "dropped",
                "2026-01-01T00:00:00Z",
            ),
            Delivery(
                message.id or "",
                "slot-a",
                "s",
                "test",
                "legacy",
                "2026-01-01T00:00:01Z",
            ),
        )
    )
    inbox = tmp_path / ".cache" / "inbox"
    (inbox / "state.json").write_text(json.dumps({"concluded_addresses": ["old-a"]}))
    relay = inbox / "relay"
    relay.mkdir()
    (relay / "state.json").write_text(json.dumps({"concluded_addresses": ["old-b"]}))

    report = transfer(tmp_path, "files", "sqlite", importing=True)

    assert report.ok
    target = SQLiteMessages(messages_db_path(tmp_path), SlotReader(tmp_path))
    with closing(sqlite3.connect(messages_db_path(tmp_path))) as db:
        assert {row[0] for row in db.execute("SELECT address FROM concluded")} == {
            "old-a",
            "old-b",
        }
    events = {row.event for row in target.deliveries()}
    assert {"delivered", "acked", "dropped", "legacy"} <= events
    assert target.unread("slot-a") == source.unread("slot-a")
    assert target.reader_position("slot-a") == source.reader_position("slot-a")


def test_import_preserves_reply_to_and_verify_checks_reply_to_parity(
    tmp_path: Path,
) -> None:
    source = _files(tmp_path)
    message = source.append(
        NewMessage(
            "sender",
            "reader",
            "info",
            "reply",
            reply_to="m-1234abcd",
        )
    )

    imported = transfer(tmp_path, "files", "sqlite", importing=True)
    target = SQLiteMessages(messages_db_path(tmp_path))
    stored = target.read_all().records[0]

    assert imported.ok
    assert stored.id == message.id
    assert stored.reply_to == "m-1234abcd"

    with closing(sqlite3.connect(messages_db_path(tmp_path))) as db:
        db.execute("UPDATE messages SET reply_to=NULL WHERE id=?", (message.id,))
        db.commit()
    report = verify(tmp_path)

    assert not report.ok
    assert "reply_to differs" in report.mismatches


def test_verify_checks_message_sequence_parity(tmp_path: Path) -> None:
    source = _files(tmp_path)
    first = source.append(NewMessage("sender", "reader", "info", "first"))
    second = source.append(NewMessage("sender", "reader", "info", "second"))
    assert transfer(tmp_path, "files", "sqlite", importing=True).ok

    with closing(sqlite3.connect(messages_db_path(tmp_path))) as db:
        db.execute("UPDATE messages SET seq=seq+10 WHERE id=?", (second.id,))
        db.commit()
    report = verify(tmp_path)

    assert first.id != second.id
    assert not report.ok
    assert "message sequence differs" in report.mismatches


def test_import_preserves_empty_reader_position_after_other_address_mail(
    tmp_path: Path,
) -> None:
    source = _files(tmp_path)
    source.append(NewMessage("sender", "other", "info", "earlier"))
    source.append(NewMessage("sender", "reader", "info", "unread"))
    source.import_reader_position("reader", None)

    report = transfer(tmp_path, "files", "sqlite", importing=True)

    assert report.ok


def test_verify_fails_when_concluded_table_differs(tmp_path: Path) -> None:
    source = _files(tmp_path)
    source.append(NewMessage("sender", "reader", "info", "body"))
    source.mark_concluded("old-address")
    assert transfer(tmp_path, "files", "sqlite", importing=True).ok
    with closing(sqlite3.connect(messages_db_path(tmp_path))) as db:
        db.execute("DELETE FROM concluded")
        db.commit()

    report = verify(tmp_path)

    assert not report.ok
    assert "concluded addresses differ" in report.mismatches


def test_delivery_parity_ignores_independent_append_order(tmp_path: Path) -> None:
    source = _files(tmp_path)
    message = source.append(NewMessage("sender", "reader", "info", "body"))
    assert transfer(tmp_path, "files", "sqlite", importing=True).ok
    left = Delivery(
        message.id or "", "reader", "s1", "test", "dropped", "2026-01-01T00:00:00Z"
    )
    right = Delivery(
        message.id or "", "reader", "s2", "test", "legacy", "2026-01-01T00:00:01Z"
    )
    source.import_deliveries((left, right))
    SQLiteMessages(messages_db_path(tmp_path)).import_deliveries((right, left))

    assert verify(tmp_path).ok


def test_import_does_not_mark_an_unverified_mismatch(tmp_path: Path) -> None:
    source = _files(tmp_path)
    source.append(NewMessage("sender", "reader", "info", "body"))
    SQLiteMessages(messages_db_path(tmp_path)).import_concluded(["sqlite-only"])

    report = transfer(tmp_path, "files", "sqlite", importing=True)

    assert not report.ok
    assert "concluded addresses differ" in report.mismatches
    assert not marker_path(tmp_path).exists()


def test_verify_on_empty_working_tree_does_not_create_sqlite(tmp_path: Path) -> None:
    report = verify(tmp_path)
    assert not report.ok
    assert "sqlite store is absent" in report.mismatches
    assert not (tmp_path / ".cache").exists()


def test_second_import_is_idempotent_and_source_bytes_and_mtimes_stay_fixed(
    tmp_path: Path,
) -> None:
    source = _files(tmp_path)
    message = source.append(NewMessage("sender", "reader", "info", "body"))
    source.claim_unread("reader", "session", "test")
    source.ack("reader", message.id or "")
    before = _snapshot_files(tmp_path)

    first = transfer(tmp_path, "files", "sqlite", importing=True)
    target = SQLiteMessages(messages_db_path(tmp_path))
    counts = (len(target.read_all().records), len(target.deliveries()))
    second = transfer(tmp_path, "files", "sqlite", importing=True)

    assert first.ok and second.ok
    assert (len(target.read_all().records), len(target.deliveries())) == counts
    assert _snapshot_files(tmp_path) == before


def test_import_rejects_same_store_and_invalid_direction(tmp_path: Path) -> None:
    with pytest.raises(Invalid, match="must differ"):
        transfer(tmp_path, "files", "files", importing=True)
    with pytest.raises(Invalid, match="only supports"):
        transfer(tmp_path, "sqlite", "files", importing=True)
    assert not marker_path(tmp_path).exists()
    assert not messages_db_path(tmp_path).exists()


def test_export_writes_copy_and_refuses_live_or_populated_destination(
    tmp_path: Path,
) -> None:
    source = _files(tmp_path)
    source.append(NewMessage("sender", "reader", "info", "body"))
    assert transfer(tmp_path, "files", "sqlite", importing=True).ok
    destination = tmp_path.parent / f"{tmp_path.name}-export"
    report = export(tmp_path, destination)
    assert report.ok
    assert (destination / ".cache" / "inbox" / "messages.jsonl").is_file()
    with pytest.raises(Invalid, match="outside the live"):
        export(tmp_path, tmp_path)
    populated = tmp_path.parent / f"{tmp_path.name}-populated"
    live_inbox = populated / ".cache" / "inbox"
    live_inbox.mkdir(parents=True)
    (live_inbox / "keep").write_text("live")
    with pytest.raises(Invalid, match="not empty"):
        export(tmp_path, populated)


def test_sync_sqlite_to_files_is_append_only_and_idempotent(tmp_path: Path) -> None:
    _files(tmp_path).append(NewMessage("sender", "reader", "info", "body"))
    assert transfer(tmp_path, "files", "sqlite", importing=True).ok
    target = SQLiteMessages(messages_db_path(tmp_path))
    target.append(NewMessage("sender", "reader", "info", "newer"))

    first = transfer(tmp_path, "sqlite", "files")
    count = len(_files(tmp_path).read_all().records)
    second = transfer(tmp_path, "sqlite", "files")

    assert first.ok and second.ok
    assert len(_files(tmp_path).read_all().records) == count == 2


def test_sync_advances_reader_position_without_rewinding(tmp_path: Path) -> None:
    source = _files(tmp_path)
    first = source.append(NewMessage("sender", "reader", "info", "first"))
    second = source.append(NewMessage("sender", "reader", "info", "second"))
    assert transfer(tmp_path, "files", "sqlite", importing=True).ok
    target = SQLiteMessages(messages_db_path(tmp_path), SlotReader(tmp_path))
    target.import_reader_position("reader", second.id)

    report = transfer(tmp_path, "sqlite", "files")

    assert report.ok
    assert source.reader_position("reader") == second.id
    assert target.reader_position("reader") == second.id
    assert source.reader_position("reader") != first.id


def test_repair_completes_database_first_and_marker_first_interruptions(
    tmp_path: Path,
) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-01-01T00:00:00+00:00")
    marker = marker_path(tmp_path)
    db_path = messages_db_path(tmp_path)
    old = json.loads(marker.read_text())
    newer = StoreModeRecord(
        "sqlite", "none", old["import_verified_at"], old["generation"] + 1
    )

    # Crash after updating SQLite meta but before the marker write.
    SQLiteMessages(db_path).write_meta("store_mode", newer.to_json())
    assert "database-first" in repair_mode(tmp_path)
    assert json.loads(marker.read_text()) == json.loads(newer.to_json())

    # A marker one generation ahead is rolled back to the durable DB record.
    later = StoreModeRecord(
        "sqlite", "files", old["import_verified_at"], newer.generation + 1
    )
    marker.write_text(later.to_json())
    assert "rolled back" in repair_mode(tmp_path)
    with closing(sqlite3.connect(db_path)) as db:
        row = db.execute("SELECT value FROM meta WHERE key='store_mode'").fetchone()
    assert json.loads(row[0]) == json.loads(newer.to_json())
    assert json.loads(marker.read_text()) == json.loads(newer.to_json())


def test_repair_refuses_to_adopt_orphan_database_or_create_database(
    tmp_path: Path,
) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-01-01T00:00:00+00:00")
    db_before = messages_db_path(tmp_path).read_bytes()
    marker_path(tmp_path).unlink()
    assert repair_mode(tmp_path) == "adopted default files mode marker"
    assert marker_path(tmp_path).exists()
    assert messages_db_path(tmp_path).read_bytes() == db_before

    other = tmp_path / "other"
    with pytest.raises(Invalid, match="metadata is absent"):
        repair_mode(other)
    assert not messages_db_path(other).exists()


@pytest.mark.parametrize("expected", ["same generation", "not adjacent"])
def test_repair_rejects_conflict_and_generation_gap_without_state_change(
    tmp_path: Path, expected: str
) -> None:
    initial = _mark_import_verified(tmp_path, verified_at="2026-01-01T00:00:00+00:00")
    marker = marker_path(tmp_path)
    db_path = messages_db_path(tmp_path)
    marker_record = StoreModeRecord(
        "files", "sqlite", initial.import_verified_at, initial.generation + 2
    )
    db_record = StoreModeRecord(
        "sqlite", "files", initial.import_verified_at, initial.generation
    )
    if expected == "same generation":
        marker_record = StoreModeRecord(
            "files", "sqlite", initial.import_verified_at, initial.generation + 1
        )
        db_record = StoreModeRecord(
            "sqlite", "none", initial.import_verified_at, initial.generation + 1
        )
    marker.write_text(marker_record.to_json(), encoding="utf-8")
    SQLiteMessages(db_path).write_meta("store_mode", db_record.to_json())
    before_marker = marker.read_bytes()
    with closing(sqlite3.connect(db_path)) as db:
        before_db = db.execute(
            "SELECT value FROM meta WHERE key='store_mode'"
        ).fetchone()[0]

    with pytest.raises(Invalid, match=expected):
        repair_mode(tmp_path)

    assert marker.read_bytes() == before_marker
    with closing(sqlite3.connect(db_path)) as db:
        after_db = db.execute(
            "SELECT value FROM meta WHERE key='store_mode'"
        ).fetchone()[0]
    assert after_db == before_db

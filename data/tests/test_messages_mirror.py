import multiprocessing
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace, TracebackType
from typing import Any, Self, cast

import pytest
import varde_data.backends.mirror.messages as mirror_module
import varde_data.locking as locking_module
import varde_data.messages as messages_module
from varde_data.backends.files.messages import FilesMessages
from varde_data.backends.mirror.messages import MirrorMessages
from varde_data.backends.sqlite.messages import factory
from varde_data.errors import Invalid, Locked
from varde_data.locking import file_lock
from varde_data.messages import open_messages
from varde_data.records.messages import Delivery, Message, NewMessage
from varde_data.repos.messages import StaticReaderResolver
from varde_data.store_mode import (
    _mark_import_verified,
    mirror_lag,
    set_store_mode,
)
from varde_data.version import Cursor


def _mirror(working: Path) -> MirrorMessages:
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    return MirrorMessages(working, "files", "sqlite")


def _sqlite_mirror(working: Path) -> MirrorMessages:
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    set_store_mode(working, "mirror-sqlite")
    return MirrorMessages(working, "sqlite", "files")


def test_mirror_down_records_lag_and_next_write_resynchronizes(tmp_path: Path) -> None:
    repository = _mirror(tmp_path)
    original = repository.mirror.import_messages
    repository.mirror.import_messages = lambda _rows: (  # pyright: ignore[reportAttributeAccessIssue]
        _ for _ in ()
    ).throw(OSError("down"))
    message = repository.append(NewMessage("sender", "reader", "info", "one", ts="t"))
    assert message.id in repository.primary.message_ids()
    assert mirror_lag(tmp_path) > 0
    assert repository.parity_report().get("mirror-failure") == 1
    assert repository.parity_report().get("lag") == 1

    repository.mirror.import_messages = original  # pyright: ignore[reportAttributeAccessIssue]
    repository.sync()
    assert repository.primary.message_ids() == repository.mirror.message_ids()
    assert mirror_lag(tmp_path) == 0


def test_mirror_preserves_ids_and_primary_errors_propagate(tmp_path: Path) -> None:
    repository = _mirror(tmp_path)
    message = repository.append(NewMessage("sender", "reader", "info", "body", ts="t"))
    assert repository.mirror.read_all().records == (message,)
    assert repository.mirror.message_ids() == repository.primary.message_ids()
    with pytest.raises(Invalid):
        repository.append(NewMessage("sender", "", "info", "bad", ts="t"))


def test_mode_flip_reads_persisted_mirror_lag(tmp_path: Path) -> None:
    repository = _mirror(tmp_path)
    repository._write_state("messages", "m-00000001", 1)
    with pytest.raises(Invalid, match="mirror lag is nonzero"):
        set_store_mode(tmp_path, "mirror-sqlite")
    assert factory(tmp_path).read_all().records == ()


def test_sync_does_not_advance_source_start_position_to_existing_head(
    tmp_path: Path,
) -> None:
    repository = _sqlite_mirror(tmp_path)
    message = repository.append(NewMessage("sender", "reader", "info", "body"))
    assert message.id is not None
    repository.primary.import_reader_position("reader", None)
    repository.mirror.import_reader_position("reader", message.id)

    repository._sync_reader_position("reader")

    assert repository.primary.reader_position("reader") is None
    assert repository.mirror.reader_position("reader") is None


def test_sync_reader_position_resolves_file_alias(tmp_path: Path) -> None:
    slots = tmp_path / ".cache" / "inbox" / "slots"
    slots.mkdir(parents=True)
    (slots / "reader.json").write_text(
        '{"slot":"reader","aliases":["reader-alias"]}', encoding="utf-8"
    )
    repository = _sqlite_mirror(tmp_path)
    message = repository.append(NewMessage("sender", "reader", "info", "body"))
    assert message.id is not None
    repository.primary.import_reader_position("reader-alias", None)
    repository.mirror.import_reader_position("reader", message.id)

    repository._sync_reader_position("reader-alias")

    assert repository.mirror.reader_position("reader") is None


def test_sync_rewinds_stale_file_cursor_to_sqlite_state(tmp_path: Path) -> None:
    repository = _sqlite_mirror(tmp_path)
    message = repository.append(NewMessage("sender", "reader", "info", "body"))
    assert message.id is not None
    end = (cast("Any", repository.mirror).inbox / "messages.jsonl").stat().st_size
    repository.mirror.commit_cursor("reader", Cursor(str(end)))
    assert repository._cursor_id(repository.mirror, "reader") == message.id
    with cast("Any", repository.primary)._connection() as db:
        db.execute("UPDATE readers SET cursor=1 WHERE reader='reader'")
        db.execute("DELETE FROM cursor_positions WHERE reader='reader'")
        db.execute("INSERT INTO cursor_positions(reader,position) VALUES ('reader',0)")
    assert repository._cursor_id(repository.primary, "reader") is None
    assert "reader" in repository._all_readers()
    assert repository._cursor_id(repository.mirror, "reader") == message.id
    assert not repository.is_synchronized()

    synchronized = repository.sync()
    assert synchronized, (
        repository.mirror_lag(),
        repository.is_synchronized(),
        repository._cursor_id(repository.primary, "reader"),
        repository._cursor_id(repository.mirror, "reader"),
        repository.primary.reader_position("reader"),
        repository.mirror.reader_position("reader"),
    )
    assert repository._cursor_id(repository.primary, "reader") is None
    assert repository._cursor_id(repository.mirror, "reader") is None


def test_stale_mirror_redirect_preserves_resolver_and_busy_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-24T00:00:00Z")
    set_store_mode(tmp_path, "mirror-files")
    resolver = StaticReaderResolver()
    stale = open_messages(
        tmp_path, "mirror-files", resolver=resolver, busy_timeout=0.17
    )
    set_store_mode(tmp_path, "mirror-sqlite")
    real_open = open_messages
    opened: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def record_open(*args, **kwargs):
        opened.append((args, kwargs))
        return real_open(*args, **kwargs)

    monkeypatch.setattr(messages_module, "open_messages", record_open)
    stale.append(NewMessage("sender", "reader", "info", "redirected"))

    assert opened == [
        ((tmp_path, "sqlite"), {"resolver": resolver, "busy_timeout": 0.17})
    ]


def test_mirror_sqlite_hook_does_not_open_files_mirror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(tmp_path, "mirror-files")
    set_store_mode(tmp_path, "mirror-sqlite")
    backend = MirrorMessages._backend

    def reject_files(working, name, resolver, timeout):
        if name == "files":
            raise AssertionError("hook path opened the files mirror")
        return backend(working, name, resolver, timeout)

    monkeypatch.setattr(MirrorMessages, "_backend", staticmethod(reject_files))
    repository = MirrorMessages(tmp_path, "sqlite", "files")
    repository.primary.append(NewMessage("sender", "reader", "info", "hello"))
    repository.primary.register_reader("reader", from_start=True)

    assert repository.claim_unread("reader", "session", "hook")
    assert repository._mirror is None


def test_existing_id_with_different_content_records_divergence(tmp_path: Path) -> None:
    repository = _mirror(tmp_path)
    source = Message("t", "sender", "reader", "info", "source", id="m-00000001")
    collision = Message("t", "sender", "reader", "info", "other", id="m-00000001")
    repository.primary.import_messages((source,))
    repository.mirror.import_messages((collision,))

    repository.append(NewMessage("sender", "reader", "info", "trigger", ts="t2"))

    assert repository.parity_report().get("divergence") == 1


@pytest.mark.parametrize("mode", ["mirror-files", "mirror-sqlite"])
def test_compare_drains_normal_hook_claim_before_recording_parity(
    tmp_path: Path, mode: str
) -> None:
    working = tmp_path / mode
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    if mode == "mirror-sqlite":
        set_store_mode(working, mode)
    repository = cast("MirrorMessages", open_messages(working, "files"))
    repository.register_reader("reader", from_start=True)
    repository.append(NewMessage("sender", "reader", "info", "hello", ts="t"))

    assert repository.claim_unread("reader", "s", "hook", "t")
    assert repository.compare()
    assert repository.parity_report().get("divergence", 0) == 0


def test_concurrent_writers_preserve_order_in_both_stores(tmp_path: Path) -> None:
    repository = _mirror(tmp_path)
    context = multiprocessing.get_context("spawn")
    processes = [
        context.Process(target=_append_messages, args=(str(tmp_path), label))
        for label in ("one", "two")
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    assert repository.primary.read_all().records == repository.mirror.read_all().records


def _append_messages(working: str, label: str) -> None:
    repository = open_messages(Path(working), "mirror-files")
    for index in range(20):
        repository.append(
            NewMessage(
                "sender", "reader", "info", f"{label}-{index}", ts=f"{label}-{index}"
            )
        )


def test_outage_recovery_preserves_unread_and_ack_sets_before_flip(
    tmp_path: Path,
) -> None:
    repository = _mirror(tmp_path)
    original = repository.mirror.import_messages
    repository.mirror.import_messages = lambda _rows: (  # pyright: ignore[reportAttributeAccessIssue]
        _ for _ in ()
    ).throw(OSError("down"))
    message = repository.append(NewMessage("sender", "reader", "info", "mail", ts="t"))
    repository.primary.record_delivery(
        Delivery(message.id or "", "reader", "session", "cli", "delivered", "t")
    )
    assert repository.primary.ack("reader", message.id or "", now="t")

    repository.mirror.import_messages = original  # pyright: ignore[reportAttributeAccessIssue]
    repository.sync()
    assert mirror_lag(tmp_path) == 0
    set_store_mode(tmp_path, "mirror-sqlite")
    active = open_messages(tmp_path, "mirror-sqlite")
    assert active.unread("reader") == repository.primary.unread("reader")
    assert active.status().acked == repository.primary.status().acked


def test_lock_timeout_lag_survives_and_resyncs(tmp_path: Path) -> None:
    repository = _mirror(tmp_path)
    entered = threading.Event()

    def append_while_locked() -> None:
        entered.set()
        repository.append(NewMessage("sender", "reader", "info", "locked", ts="t"))

    with file_lock(repository._lock_path, timeout=0.1):
        writer = threading.Thread(target=append_while_locked)
        writer.start()
        assert entered.wait(timeout=1)
        writer.join(timeout=1)
        assert not writer.is_alive()
        assert mirror_lag(tmp_path) > 0
    assert repository.sync()
    assert mirror_lag(tmp_path) == 0
    assert repository.primary.read_all().records == repository.mirror.read_all().records


def test_unlocked_primary_write_re_marks_pending_after_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _mirror(tmp_path)
    original_mark = repository._mark_pending
    marks: list[int | None] = []

    def track_mark(method: str, args: tuple[object, ...]) -> int | None:
        epoch = original_mark(method, args)
        marks.append(epoch)
        return epoch

    class FailingLock:
        def __enter__(self) -> None:
            raise Locked("simulated mirror lock timeout")

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(repository, "_mark_pending", track_mark)
    monkeypatch.setattr(
        mirror_module, "file_lock", lambda *_args, **_kwargs: FailingLock()
    )

    message = repository.append(
        NewMessage("sender", "reader", "info", "unlocked", ts="t")
    )

    assert message.id in repository.primary.message_ids()
    assert len(marks) == 2
    assert mirror_lag(tmp_path) > 0


def test_sync_keeps_all_streams_pending_when_replay_is_incomplete(
    tmp_path: Path,
) -> None:
    repository = _mirror(tmp_path)
    message = repository.primary.append(
        NewMessage("sender", "reader", "info", "primary-only", ts="t")
    )
    repository._mark_pending("append", ())
    original_import = repository.mirror.import_messages
    repository.mirror.import_messages = lambda _rows: None  # type: ignore[method-assign]

    assert not repository.sync()
    assert mirror_lag(tmp_path) > 0
    assert message.id not in repository.mirror.message_ids()

    repository.mirror.import_messages = original_import  # type: ignore[method-assign]
    assert repository.sync()
    assert repository.is_synchronized()
    assert mirror_lag(tmp_path) == 0


def test_sync_repairs_divergence_even_when_pending_state_was_lost(
    tmp_path: Path,
) -> None:
    repository = _mirror(tmp_path)
    message = repository.primary.append(
        NewMessage("sender", "reader", "info", "primary-only", ts="t")
    )

    assert repository.sync()

    assert message.id in repository.mirror.message_ids()
    assert repository.is_synchronized()
    assert mirror_lag(tmp_path) == 0


def test_files_reader_discovery_ignores_atomic_cursor_temps(tmp_path: Path) -> None:
    repository = _mirror(tmp_path)
    cursors = repository.primary.inbox / "cursors"  # pyright: ignore[reportAttributeAccessIssue]
    cursors.mkdir(parents=True)
    (cursors / "reader").write_text("12", encoding="ascii")
    (cursors / ".reader.1234.tmp").write_text("7", encoding="ascii")

    assert MirrorMessages._readers(repository.primary) == {"reader"}


def test_pending_epoch_clear_cannot_overwrite_a_concurrent_mark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _mirror(tmp_path)
    initial_epoch = repository._mark_pending("append", ())
    assert initial_epoch is not None
    checked_epoch = threading.Event()
    allow_clear = threading.Event()
    mark_started = threading.Event()
    mark_lock_attempted = threading.Event()
    mark_finished = threading.Event()
    clear_results: list[bool] = []
    original_connect = repository._connect

    class PausingConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection

        def __enter__(self) -> Self:
            self.connection.__enter__()
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool | None:
            return self.connection.__exit__(exc_type, exc, traceback)

        def close(self) -> None:
            self.connection.close()

        def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
            if (
                threading.current_thread().name == "mark-pending"
                and sql == "BEGIN IMMEDIATE"
            ):
                mark_lock_attempted.set()
            cursor = self.connection.execute(sql, parameters)
            if (
                threading.current_thread().name == "clear-pending"
                and "SELECT position FROM mirror_state WHERE stream='epoch'" in sql
            ):
                checked_epoch.set()
                if not allow_clear.wait(5):
                    raise TimeoutError("test did not release pending clear")
            return cursor

        def executemany(self, sql: str, rows: Any) -> sqlite3.Cursor:
            return self.connection.executemany(sql, rows)

    def connect() -> Any:
        connection = original_connect()
        if threading.current_thread().name in {"clear-pending", "mark-pending"}:
            return PausingConnection(connection)
        return connection

    monkeypatch.setattr(repository, "_connect", connect)

    def clear_pending() -> None:
        clear_results.append(
            repository._clear_pending(
                {"messages"}, set(), initial_epoch, {"messages:files": "0"}
            )
        )

    def mark_pending() -> None:
        mark_started.set()
        repository._mark_pending("append", ())
        mark_finished.set()

    clearer = threading.Thread(target=clear_pending, name="clear-pending")
    marker = threading.Thread(target=mark_pending, name="mark-pending")
    clearer.start()
    assert checked_epoch.wait(2)
    marker.start()
    assert mark_started.wait(2)
    assert mark_lock_attempted.wait(2)
    marker_was_blocked = not mark_finished.wait(0.1)
    allow_clear.set()
    clearer.join(2)
    marker.join(2)

    assert not clearer.is_alive()
    assert not marker.is_alive()
    assert marker_was_blocked
    assert clear_results == [True]
    assert mirror_lag(tmp_path) > 0


def test_sqlite_delivery_progress_does_not_skip_a_concurrent_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _sqlite_mirror(tmp_path)
    writer = factory(tmp_path)
    primary = repository.primary
    original_connection = primary._connection  # pyright: ignore[reportAttributeAccessIssue]
    injected = False
    delivery = Delivery("m-concurrent", "reader", "session", "hook", "delivered", "t")

    class ResultProxy:
        def __init__(self, cursor: sqlite3.Cursor) -> None:
            self.cursor = cursor

        def fetchall(self) -> list[sqlite3.Row]:
            nonlocal injected
            rows = self.cursor.fetchall()
            if not injected:
                injected = True
                writer.import_deliveries((delivery,))
            return rows

    class ConnectionProxy:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection

        def execute(self, sql: str, parameters: Any = ()) -> Any:
            cursor = self.connection.execute(sql, parameters)
            if "SELECT * FROM deliveries WHERE seq>? ORDER BY seq" in sql:
                return ResultProxy(cursor)
            return cursor

        def __enter__(self) -> Self:
            self.connection.__enter__()
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            traceback: TracebackType | None,
        ) -> bool | None:
            return self.connection.__exit__(exc_type, exc, traceback)

    @contextmanager
    def connection():
        with original_connection() as db:
            yield ConnectionProxy(db)

    monkeypatch.setattr(primary, "_connection", connection)

    first_rows, first_position = repository._repository_deliveries_after(primary, "0")

    assert first_rows == ()
    assert first_position == "0"
    monkeypatch.setattr(primary, "_connection", original_connection)
    second_rows, second_position = repository._repository_deliveries_after(primary, "0")
    assert second_rows == (delivery,)
    assert second_position == "1"


def test_sqlite_primary_sync_aligns_reader_and_files_cursor_after_hook_claim(
    tmp_path: Path,
) -> None:
    repository = _sqlite_mirror(tmp_path)
    repository.append(NewMessage("sender", "reader", "info", "hook mail", ts="t"))
    assert len(repository.claim_unread("reader", "hook", "hook", "t")) == 1

    assert repository.sync()

    assert repository.primary.reader_position(
        "reader"
    ) == repository.mirror.reader_position("reader")
    assert repository._cursor_id(repository.primary, "reader") == repository._cursor_id(
        repository.mirror, "reader"
    )
    assert repository.is_synchronized()


def test_flip_drains_primary_write_when_pending_record_was_lost(tmp_path: Path) -> None:
    repository = _mirror(tmp_path)
    repository.primary.append(
        NewMessage("sender", "reader", "info", "unmirrored", ts="t")
    )
    assert mirror_lag(tmp_path) == 0
    result = set_store_mode(tmp_path, "mirror-sqlite")

    assert result.primary == "sqlite"
    assert repository.primary.read_all().records == repository.mirror.read_all().records


def test_commit_cursor_for_reader_without_deliveries_is_replayed(
    tmp_path: Path,
) -> None:
    repository = _mirror(tmp_path)
    repository.append(NewMessage("sender", "reader", "info", "one", ts="t1"))
    repository.append(NewMessage("sender", "reader", "info", "two", ts="t2"))
    repository.commit_cursor("reader", repository.primary.head())
    assert repository.compare()


@pytest.mark.slow
def test_hook_claim_incremental_mirror_sync_matches_plain_store(tmp_path: Path) -> None:
    mirrored = _sqlite_mirror(tmp_path / "mirrored")
    plain = factory(tmp_path / "plain")
    for index in range(500):
        message = NewMessage(
            "sender", "reader", "info", f"message-{index}", ts=f"t-{index}"
        )
        mirrored.append(message)
        plain.append(message)
    mirrored.register_reader("reader", from_start=True)
    plain.register_reader("reader", from_start=True)

    plain_result = plain.claim_unread("reader", "session", "hook", "t")
    mirror_result = mirrored.claim_unread("reader", "session", "hook", "t")

    assert len(plain_result) == len(mirror_result) == 500
    # Compare both stores after explicitly synchronizing the large unread batch.
    assert mirrored.sync()
    assert mirror_lag(tmp_path / "mirrored") == 0
    assert mirrored.compare()


@pytest.mark.parametrize("factory", [_mirror, _sqlite_mirror])
def test_empty_hook_claim_does_not_mark_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    factory: Any,
) -> None:
    repository = factory(tmp_path)
    monkeypatch.setattr(
        repository,
        "_mark_pending",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected write")),
    )
    monkeypatch.setattr(
        repository,
        "_mark_pending_in",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected write")),
    )
    assert repository.claim_unread("reader", "session", "hook", "t") == ()
    assert repository.mirror_lag() == 0


def test_hook_claim_pending_row_is_replayed_by_next_write(tmp_path: Path) -> None:
    repository = _mirror(tmp_path)
    repository.append(NewMessage("sender", "reader", "info", "mail", ts="t"))
    assert repository.claim_unread("reader", "session", "hook", "t")
    assert repository.mirror_lag() > 0

    repository.append(NewMessage("sender", "reader", "info", "next", ts="t2"))

    assert repository.mirror_lag() == 0


@pytest.mark.parametrize("mirror", [False, True], ids=["files", "mirror-files"])
def test_files_claim_lock_timeout_is_configurable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mirror: bool
) -> None:
    if mirror:
        _mark_import_verified(tmp_path, verified_at="2026-10-23T00:00:00Z")
        set_store_mode(tmp_path, "mirror-files")
        repository = MirrorMessages(tmp_path, "files", "sqlite", busy_timeout=0.02)
        files = repository.primary
        assert isinstance(files, FilesMessages)
    else:
        files = FilesMessages(tmp_path, lock_timeout=0.02)
        repository = files
    repository.append(NewMessage("sender", "reader", "info", "mail", ts="t"))

    clock = {"now": 0.0}
    sleeps: list[float] = []

    def sleep(delay: float) -> None:
        sleeps.append(delay)
        clock["now"] += delay

    monkeypatch.setattr(
        locking_module,
        "time",
        SimpleNamespace(monotonic=lambda: clock["now"], sleep=sleep),
    )

    with file_lock(files._lock("reader"), timeout=0.1), pytest.raises(Locked):
        repository.claim_unread("reader", "session", "hook", "t")
    assert clock["now"] == pytest.approx(0.02)
    assert sleeps == [0.01, 0.01]

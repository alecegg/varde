from __future__ import annotations

import json
import multiprocessing
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path
from typing import cast

import pytest
from varde_data import store_mode
from varde_data.backends.files.messages import FilesMessages
from varde_data.backends.mirror.messages import MirrorMessages
from varde_data.backends.sqlite.messages import SQLiteMessages
from varde_data.errors import Invalid, Locked
from varde_data.locking import file_lock
from varde_data.messages import open_messages
from varde_data.messages_transfer import repair_mode
from varde_data.records.messages import NewMessage
from varde_data.store_mode import (
    StoreModeInvalid,
    StoreModeRecord,
    _mark_import_verified,
    marker_path,
    read_store_mode,
    set_store_mode,
    transition_allowed,
)


def _race_to_mirror_files(working: str, barrier, results) -> None:
    barrier.wait()
    try:
        result = set_store_mode(Path(working), "mirror-files")
    except (Invalid, Locked) as exc:
        results.put(type(exc).__name__)
    else:
        results.put(f"ok:{result.generation}")


def test_sqlite_config_without_import_marker_fails(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    monkeypatch.setenv("VARDE_DATA_MESSAGES_BACKEND", "sqlite")

    from varde_data.config import load_data_config

    backend = load_data_config(tmp_path / "config").backends["messages"]
    with pytest.raises(Invalid, match="run varde msg store import"):
        open_messages(working, backend)


def test_config_does_not_override_files_primary_marker(
    tmp_path: Path, monkeypatch
) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    monkeypatch.setenv("VARDE_DATA_MESSAGES_BACKEND", "sqlite")

    from varde_data.config import load_data_config

    backend = load_data_config(tmp_path / "config").backends["messages"]
    assert isinstance(open_messages(working, backend), FilesMessages)


def test_no_marker_keeps_default_files_open_without_creating_inbox(
    tmp_path: Path,
) -> None:
    working = tmp_path / "working"

    assert isinstance(open_messages(working, "files"), FilesMessages)
    assert not (working / ".cache").exists()


def test_unreadable_present_marker_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    original_read_text = Path.read_text

    def fail_marker_read(path: Path, *args, **kwargs):
        if path == marker_path(working):
            raise PermissionError("marker denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_marker_read)
    with pytest.raises(Invalid, match="cannot read message store mode marker") as exc:
        open_messages(working, "files")
    assert isinstance(exc.value, StoreModeInvalid)
    assert isinstance(exc.value, ValueError)


@pytest.mark.parametrize("payload", [b"{", b"\xff"])
def test_corrupt_present_marker_fails_closed(tmp_path: Path, payload: bytes) -> None:
    path = marker_path(tmp_path / "working")
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)

    with pytest.raises(Invalid, match="invalid message store mode marker"):
        open_messages(path.parents[2], "files")


def test_non_directory_cache_path_preserves_default_files_open(tmp_path: Path) -> None:
    working = tmp_path / "working"
    working.mkdir()
    (working / ".cache").write_text("legacy content", encoding="utf-8")

    assert isinstance(open_messages(working, "files"), FilesMessages)


def test_missing_marker_with_store_metadata_fails_closed(tmp_path: Path) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    marker_path(working).unlink()

    with pytest.raises(Invalid, match="marker is missing"):
        FilesMessages(working)


def test_open_files_accepts_orphan_default_files_none_record(tmp_path: Path) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    marker_path(working).unlink()

    assert isinstance(open_messages(working, "files"), FilesMessages)
    assert repair_mode(working) == "adopted default files mode marker"
    assert read_store_mode(working) == StoreModeRecord(
        "files", "none", "2026-10-23T00:00:00Z", 1
    )


def test_repair_mode_requires_force_for_nondefault_orphan_record(
    tmp_path: Path,
) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    marker_path(working).unlink()

    with pytest.raises(Invalid, match="--force-adopt"):
        open_messages(working, "files")
    with pytest.raises(Invalid, match="--force-adopt"):
        repair_mode(working)
    assert "force-adopt" in repair_mode(working, force_adopt=True)
    assert read_store_mode(working) is not None


@pytest.mark.parametrize("backend", ["sqlite", "mirror-files", "mirror-sqlite"])
def test_sqlite_and_mirror_modes_require_verified_marker(
    tmp_path: Path, backend: str
) -> None:
    with pytest.raises(Invalid, match="run varde msg store import"):
        open_messages(tmp_path / "working", backend)


def test_files_opener_fails_after_sqlite_only_flip(tmp_path: Path) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    set_store_mode(working, "mirror-sqlite")
    set_store_mode(working, "sqlite")

    with pytest.raises(Locked, match="SQLite-primary"):
        FilesMessages(working)


def test_illegal_store_mode_transition_is_refused(tmp_path: Path) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    assert transition_allowed("files", "mirror-files")
    assert not transition_allowed("files", "sqlite")

    with pytest.raises(Invalid, match="illegal message store mode transition"):
        set_store_mode(working, "sqlite")


def test_import_verification_preserves_later_mode(tmp_path: Path) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    set_store_mode(working, "mirror-sqlite")

    refreshed = _mark_import_verified(working, verified_at="2026-10-24T00:00:00Z")

    assert refreshed == StoreModeRecord("sqlite", "files", "2026-10-24T00:00:00Z", 4)
    assert read_store_mode(working) == refreshed


def test_store_mode_transition_refuses_when_mirror_lags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "working"
    initial = _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    monkeypatch.setattr(store_mode, "mirror_lag", lambda _working, *, verify=False: 2)

    with pytest.raises(Invalid, match="mirror lag is nonzero"):
        set_store_mode(working, "mirror-files")
    assert read_store_mode(working) == initial


def test_concurrent_mode_changes_use_generation_compare_and_swap(
    tmp_path: Path,
) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_race_to_mirror_files,
            args=(str(working), barrier, results),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)

    assert all(process.exitcode == 0 for process in processes)
    assert sum(outcome.startswith("ok:") for outcome in outcomes) == 1
    marker = read_store_mode(working)
    assert marker is not None
    assert marker.generation == 2


def test_interrupted_db_first_write_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "working"
    original = _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")

    def fail_marker_write(*_args, **_kwargs):
        raise OSError("simulated crash before marker replacement")

    monkeypatch.setattr(store_mode, "atomic_write", fail_marker_write)
    with pytest.raises(Invalid, match="could not write message store mode marker"):
        set_store_mode(working, "mirror-files")

    monkeypatch.undo()
    with pytest.raises(Invalid, match="interrupted store mode flip"):
        read_store_mode(working)
    assert (
        json.loads(marker_path(working).read_text(encoding="utf-8"))["generation"]
        == original.generation
    )


@pytest.mark.parametrize("failure_point", ["database", "marker"])
def test_mirror_flip_checks_lag_and_recovers_each_interrupted_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    original = read_store_mode(working)
    assert original is not None
    real_mirror_lag = store_mode.mirror_lag
    checked_lag = False

    def check_lag(path: Path, *, verify: bool = False) -> int:
        nonlocal checked_lag
        checked_lag = verify
        return real_mirror_lag(path, verify=verify)

    monkeypatch.setattr(store_mode, "mirror_lag", check_lag)
    if failure_point == "database":
        monkeypatch.setattr(
            SQLiteMessages,
            "write_meta",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("simulated crash before SQLite metadata write")
            ),
        )
    else:
        monkeypatch.setattr(
            store_mode,
            "atomic_write",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("simulated crash before marker write")
            ),
        )

    with pytest.raises((Invalid, OSError)):
        set_store_mode(working, "mirror-sqlite")

    assert checked_lag
    if failure_point == "database":
        assert read_store_mode(working) == original
    else:
        with pytest.raises(Invalid, match="interrupted store mode flip"):
            read_store_mode(working)
        monkeypatch.undo()
        repair_mode(working)
        repaired = read_store_mode(working)
        assert repaired is not None
        assert repaired.primary == "sqlite"
        set_store_mode(working, "mirror-files")


def test_open_messages_waits_for_live_mode_flip(tmp_path: Path) -> None:
    working = tmp_path / "working"
    original = _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    next_record = StoreModeRecord(
        "files", "sqlite", original.import_verified_at, original.generation + 1
    )
    marker_written = threading.Event()
    finish_flip = threading.Event()

    def flip() -> None:
        with file_lock(working / store_mode._LOCK, timeout=2):
            from varde_data.backends.sqlite.messages import factory

            factory(working).write_meta("store_mode", next_record.to_json())
            marker_written.set()
            assert finish_flip.wait(5)
            store_mode.atomic_write(
                marker_path(working), next_record.to_json().encode(), mode=0o600
            )

    transition = threading.Thread(target=flip)
    transition.start()
    assert marker_written.wait(5)
    result: list[object] = []
    reader = threading.Thread(
        target=lambda: result.append(open_messages(working, "files"))
    )
    reader.start()
    time.sleep(0.05)
    assert reader.is_alive()
    finish_flip.set()
    transition.join(5)
    reader.join(5)

    assert not transition.is_alive()
    assert not reader.is_alive()
    assert not isinstance(result[0], BaseException)
    assert read_store_mode(working) == next_record


def test_open_messages_mode_lock_wait_is_bounded(tmp_path: Path) -> None:
    working = tmp_path / "working"
    with file_lock(working / store_mode._LOCK, timeout=1):
        started = time.monotonic()
        with pytest.raises(Locked, match="message store mode is busy"):
            open_messages(working, "files", busy_timeout=0.04)
        assert time.monotonic() - started < 0.2


def test_mode_flip_drains_pending_mirror_while_holding_write_lock(
    tmp_path: Path,
) -> None:
    working = tmp_path / "working"
    _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    set_store_mode(working, "mirror-files")
    repository = cast("MirrorMessages", open_messages(working, "mirror-files"))
    message = NewMessage("writer", "reader", "info", "pending before cutover")
    repository.primary.append(message)
    repository._mark_pending("append", (message,))
    lock_held = threading.Event()
    release_lock = threading.Event()
    result: list[StoreModeRecord] = []

    def hold_writer_lock() -> None:
        with file_lock(working / ".cache/inbox/mirror.lock", timeout=2):
            lock_held.set()
            assert release_lock.wait(5)

    holder = threading.Thread(target=hold_writer_lock)
    holder.start()
    assert lock_held.wait(5)
    transition = threading.Thread(
        target=lambda: result.append(set_store_mode(working, "mirror-sqlite"))
    )
    transition.start()
    time.sleep(0.05)
    assert transition.is_alive()
    release_lock.set()
    holder.join(5)
    transition.join(10)

    assert not holder.is_alive()
    assert not transition.is_alive()
    assert result == [read_store_mode(working)]
    assert result[0].primary == "sqlite"
    reopened = cast("MirrorMessages", open_messages(working, "mirror-sqlite"))
    assert reopened.read_all().records == reopened.mirror.read_all().records


def test_invalid_primary_mirror_pair_raises_invalid(tmp_path: Path) -> None:
    path = marker_path(tmp_path / "working")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "primary": "sqlite",
                "mirror": "sqlite",
                "import_verified_at": "2026-10-23T00:00:00Z",
                "generation": 1,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(Invalid, match="invalid primary and mirror"):
        read_store_mode(path.parents[2])


def test_store_mode_marker_round_trips_to_sqlite_meta(tmp_path: Path) -> None:
    working = tmp_path / "working"
    expected = _mark_import_verified(working, verified_at="2026-10-23T00:00:00Z")
    path = marker_path(working)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": store_mode.STORE_MODE_MARKER_VERSION,
        "primary": "files",
        "mirror": "none",
        "import_verified_at": "2026-10-23T00:00:00Z",
        "generation": 1,
    }
    assert read_store_mode(working) == expected

    db_path = working / ".cache" / "inbox" / "messages.sqlite3"
    with closing(sqlite3.connect(db_path)) as db:
        value = db.execute("SELECT value FROM meta WHERE key='store_mode'").fetchone()[
            0
        ]
    assert json.loads(value) == json.loads(path.read_text(encoding="utf-8"))

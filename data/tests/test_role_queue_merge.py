from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from varde_data.backends.sqlite.queue_schema import configure_store
from varde_data.errors import Invalid, Locked
from varde_data.role_queue_merge import (
    QUEUE_TABLES,
    merge_role_queue,
    rollback_role_queue,
)
from varde_data.store_mode import read_store_mode

LEGACY = Path(".cache/data/queue.sqlite3")
INBOX = Path(".cache/inbox/messages.sqlite3")
VERSION = Path(".cache/data/queue.version")


def _legacy_queue(root: Path) -> Path:
    database = root / LEGACY
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        configure_store(connection)
        connection.execute("DROP TABLE queue_store_meta")
        connection.execute("PRAGMA user_version=3")
        connection.execute("INSERT INTO meta(key,value) VALUES('store_mode','sqlite')")
        connection.execute(
            "INSERT INTO queue_items "
            "(id,plan_dir,findings,owned_files,state,claimed_by,claim_expires_at,"
            "claim_generation,claim_epoch,queue_name) "
            "VALUES('work-1','plan','[]','file.py','claimed','builder-1',"
            "'2026-10-29T10:00:00Z',7,3,'roles/builder')"
        )
        connection.execute(
            "INSERT INTO queue_events(item_id,at,actor,kind,"
            "from_state,to_state,source) "
            "VALUES('work-1','2026-10-28T10:00:00Z','builder-1','claimed',"
            "'queued','claimed','test')"
        )
        connection.execute(
            "INSERT INTO queue_meta(queue_name,last_export_hash,header) "
            "VALUES('roles/builder','hash','header')"
        )
        connection.execute(
            "INSERT INTO plan_state(plan_dir,status,status_at,owner) "
            "VALUES('plan','active','2026-10-28','builder-1')"
        )
        connection.execute(
            "INSERT INTO task_state(plan_dir,task_id,status,status_at) "
            "VALUES('plan','T1','in_progress','2026-10-28')"
        )
        connection.execute(
            "INSERT INTO slots(slot_id,plan_id,role,lease_s,state,epoch) "
            "VALUES('slot-1','plan','builder',120,'active',3)"
        )
        connection.execute(
            "INSERT INTO slot_events(slot_id,at,actor,kind,epoch,detail) "
            "VALUES('slot-1','2026-10-28T10:00:00Z','builder-1','registered',3,'{}')"
        )
    (root / VERSION).parent.mkdir(parents=True, exist_ok=True)
    (root / VERSION).write_text("3\n")
    return database


def _rows(database: Path, table: str) -> list[tuple[object, ...]]:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            f'SELECT * FROM "{table}" ORDER BY 1'  # noqa: S608
        ).fetchall()


def test_merge_preserves_queue_rows_and_claim_fencing_in_files_mail_mode(
    tmp_path: Path,
) -> None:
    legacy = _legacy_queue(tmp_path)
    before = {table: _rows(legacy, table) for table in QUEUE_TABLES}

    report = merge_role_queue(tmp_path)

    assert report.verified
    target = tmp_path / INBOX
    assert {table: _rows(target, table) for table in QUEUE_TABLES} == before
    assert report.backup is not None
    assert report.backup.with_suffix(".sqlite3.json").is_file()
    assert report.row_counts is not None
    assert report.row_counts["queue_items"] == 1
    item = before["queue_items"][0]
    assert item[15:19] == (
        "builder-1",
        "2026-10-29T10:00:00Z",
        7,
        3,
    )
    assert (tmp_path / VERSION).read_text() == "4\n"
    assert legacy.exists()
    assert read_store_mode(tmp_path) is None

    from varde_data.queue import open_queue
    from varde_data.records.queue import QueueItemInput

    queue = open_queue(tmp_path)
    item = queue.enqueue(
        QueueItemInput("work-2", "plan", role="builder", queue_name="roles/builder")
    )
    assert queue.get("roles/builder", item.id) == item


def test_role_queue_open_refuses_unmerged_v3_marker(tmp_path: Path) -> None:
    _legacy_queue(tmp_path)

    from varde_data.queue import open_queue

    with pytest.raises(Invalid, match="merge-role-inbox"):
        open_queue(tmp_path)


def test_ready_check_retries_a_busy_unified_database(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_data import queue_mode_lock

    database = tmp_path / INBOX
    database.parent.mkdir(parents=True)
    database.touch()
    (tmp_path / VERSION).parent.mkdir(parents=True)
    (tmp_path / VERSION).write_text("4\n")

    def busy_connect(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(queue_mode_lock.sqlite3, "connect", busy_connect)
    with pytest.raises(Locked, match="busy"):
        queue_mode_lock.require_role_queue_ready(tmp_path)


def test_ready_check_marks_unmerged_marker_as_invalid(tmp_path: Path) -> None:
    from varde_data.queue_mode_lock import require_role_queue_ready

    (tmp_path / VERSION).parent.mkdir(parents=True)
    (tmp_path / VERSION).write_text("3\n")
    with pytest.raises(Invalid, match="merge-role-inbox"):
        require_role_queue_ready(tmp_path)


def test_queue_status_exposes_actionable_pending_migration(tmp_path: Path) -> None:
    _legacy_queue(tmp_path)

    from varde_data.queue_store import status

    report = status(tmp_path)

    assert report["migration_pending"] is True
    assert report["migration_message"] == (
        "queue migration pending: run varde plan queue merge-role-inbox"
    )


def test_rollback_copies_current_queue_rows_back_and_restores_v3_marker(
    tmp_path: Path,
) -> None:
    legacy = _legacy_queue(tmp_path)
    merge_role_queue(tmp_path)
    target = tmp_path / INBOX
    with sqlite3.connect(target) as connection:
        connection.execute(
            "UPDATE queue_items SET state='merged',claim_generation=8 WHERE id='work-1'"
        )
    current = _rows(target, "queue_items")

    rollback_role_queue(tmp_path)

    assert _rows(legacy, "queue_items") == current
    assert (tmp_path / VERSION).read_text() == "3\n"
    assert _rows(target, "queue_items") == []
    merge_role_queue(tmp_path)
    assert _rows(tmp_path / INBOX, "queue_items") == current


def test_interrupted_copy_can_be_retried_safely(tmp_path: Path) -> None:
    legacy = _legacy_queue(tmp_path)
    code = (
        "import os, pathlib; "
        "from varde_data import role_queue_merge as merge; "
        "merge._checkpoint = lambda step: os._exit(77) "
        "if step == 'after_copy' else None; "
        "merge.merge_role_queue(pathlib.Path(os.environ['WORKING']))"
    )
    result = subprocess.run(  # noqa: S603 - fixed crash-injection snippet.
        [sys.executable, "-c", code],
        check=False,
        env={**os.environ, "WORKING": str(tmp_path)},
    )
    assert result.returncode == 77
    assert (tmp_path / VERSION).read_text() == "3\n"
    assert _rows(tmp_path / INBOX, "queue_items") == _rows(legacy, "queue_items")

    report = merge_role_queue(tmp_path)

    assert report.verified
    assert (tmp_path / VERSION).read_text() == "4\n"
    assert _rows(tmp_path / INBOX, "queue_items") == _rows(legacy, "queue_items")


def test_mail_writes_can_run_during_queue_claims(tmp_path: Path) -> None:
    from varde_data.backends.sqlite.messages import SQLiteMessages
    from varde_data.queue import open_queue
    from varde_data.records.messages import NewMessage
    from varde_data.records.queue import QueueItemInput

    _legacy_queue(tmp_path)
    merge_role_queue(tmp_path)
    queue = open_queue(tmp_path)
    messages = SQLiteMessages(tmp_path / INBOX)
    start = Barrier(2)
    for index in range(12):
        queue.enqueue(
            QueueItemInput(
                f"proof-work-{index}", "plan", role="builder", queue_name="roles"
            )
        )

    def claim_all() -> list[str]:
        claimed = []
        start.wait()
        while item := queue.claim(
            "roles", worker="builder", lease_s=60, now="2026-10-28T12:00:00Z"
        ):
            claimed.append(item.id)
        return claimed

    def write_mail() -> list[str]:
        start.wait()
        ids = [
            messages.append(NewMessage("main", "builder", "info", str(index))).id
            for index in range(12)
        ]
        return [message_id for message_id in ids if message_id is not None]

    with ThreadPoolExecutor(max_workers=2) as workers:
        claims = workers.submit(claim_all)
        mail = workers.submit(write_mail)
        claimed_ids, message_ids = claims.result(), mail.result()

    assert len(claimed_ids) == 12
    assert len(message_ids) == 12
    assert len(set(claimed_ids)) == 12
    assert len(set(message_ids)) == 12


def test_merge_rollback_keeps_existing_message_rows(tmp_path: Path) -> None:
    from varde_data.backends.sqlite.messages import SQLiteMessages
    from varde_data.records.messages import NewMessage

    legacy = _legacy_queue(tmp_path)
    target = tmp_path / INBOX
    messages = SQLiteMessages(target)
    messages.append(NewMessage("main", "role:builder", "info", "preserve inbox"))

    merge_role_queue(tmp_path)
    rollback_role_queue(tmp_path)

    assert _rows(legacy, "queue_items")[0][0] == "work-1"
    assert [message.text for message in messages.read_all().records] == [
        "preserve inbox"
    ]


def test_failed_merge_restores_inbox_and_leaves_queue_marker(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_data import role_queue_merge
    from varde_data.backends.sqlite.messages import SQLiteMessages
    from varde_data.records.messages import NewMessage

    _legacy_queue(tmp_path)
    target = tmp_path / INBOX
    messages = SQLiteMessages(target)
    messages.append(NewMessage("main", "role:builder", "info", "unchanged"))

    def fail_copy(*args, **kwargs):
        raise OSError("simulated table copy failure")

    monkeypatch.setattr(role_queue_merge, "_copy_queue_tables", fail_copy)
    with pytest.raises(OSError, match="simulated table copy failure"):
        merge_role_queue(tmp_path)

    assert (tmp_path / VERSION).read_text() == "3\n"
    assert [message.text for message in messages.read_all().records] == ["unchanged"]
    with sqlite3.connect(target) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name='queue_items'"
            ).fetchone()
            is None
        )

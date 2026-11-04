from __future__ import annotations

import json
import multiprocessing
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

from varde_data.locking import file_lock
from varde_data.messages import messages_db_path, open_messages
from varde_data.records.messages import NewMessage
from varde_data.store_mode import _mark_import_verified, set_store_mode
from varde_workflow.binding import BindingStore


def _hold_write_lock(database: str, ready, release) -> None:
    connection = sqlite3.connect(database, timeout=0)
    connection.execute("BEGIN IMMEDIATE")
    ready.set()
    release.wait(10)
    connection.rollback()
    connection.close()


def test_hook_returns_within_sqlite_busy_timeout(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.setenv("VARDE_DATA_MESSAGES_BACKEND", "sqlite")
    binding = BindingStore(working)
    moment = datetime(2026, 10, 24, tzinfo=UTC)
    marker = binding.issue("worker", now=moment)
    assert binding.redeem(marker, "session", "claude", str(working), now=moment)
    _mark_import_verified(working, verified_at="2026-10-24T00:00:00Z")
    set_store_mode(working, "mirror-files")
    set_store_mode(working, "mirror-sqlite")
    set_store_mode(working, "sqlite")
    repository = open_messages(working, "sqlite")
    repository.register_reader("worker", from_start=True)
    repository.append(NewMessage("sender", "worker", "info", "blocked"))

    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_write_lock,
        args=(str(messages_db_path(working)), ready, release),
    )
    process.start()
    assert ready.wait(5)
    from varde.glue import inbox_hook

    default_timeout = inbox_hook._PROMPT_SQLITE_BUSY_TIMEOUT
    original_bounded_messages = inbox_hook._bounded_messages
    observed_timeouts: list[float] = []

    def use_short_busy_timeout(path, config, *, busy_timeout=default_timeout):
        observed_timeouts.append(busy_timeout)
        return original_bounded_messages(path, config, busy_timeout=0.05)

    monkeypatch.setattr(inbox_hook, "_bounded_messages", use_short_busy_timeout)
    try:
        started = time.monotonic()
        result = inbox_hook.prompt_inbox(
            "claude",
            json.dumps({"session_id": "session", "prompt": "hello"}).encode(),
            banner_enabled=False,
        )
        elapsed = time.monotonic() - started
    finally:
        release.set()
        process.join(5)

    assert process.exitcode == 0
    assert result == []
    assert observed_timeouts == [default_timeout]
    assert elapsed < 5


def test_hook_skips_when_mode_flip_holds_exclusive_lock(
    tmp_path: Path, monkeypatch
) -> None:
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    binding = BindingStore(working)
    moment = datetime(2026, 10, 24, tzinfo=UTC)
    marker = binding.issue("worker", now=moment)
    assert binding.redeem(marker, "session", "claude", str(working), now=moment)
    _mark_import_verified(working, verified_at="2026-10-24T00:00:00Z")

    from varde.glue.inbox_hook import prompt_inbox

    with file_lock(working / ".cache/inbox/store-mode.lock", timeout=1):
        started = time.monotonic()
        result = prompt_inbox(
            "claude",
            json.dumps({"session_id": "session", "prompt": "hello"}).encode(),
            banner_enabled=False,
        )
        elapsed = time.monotonic() - started

    assert result == []
    assert elapsed < 2.5

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import cast
from unittest.mock import patch

from varde_data.errors import Locked
from varde_data.messages import open_messages, touch_relay_wake
from varde_data.records.messages import NewMessage
from varde_data.store_mode import _mark_import_verified, set_store_mode
from varde_runner.relay import RelayCLIProtocol, RelayWorker
from varde_runner.supervisor import SendOutcome
from varde_runner.web.cache import InboxStoreCache, watched_files_signature


def test_idle_runner_reads_do_not_change_sqlite_dashboard_signature(
    tmp_path: Path,
) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-24T00:00:00Z")
    set_store_mode(tmp_path, "mirror-files")
    set_store_mode(tmp_path, "mirror-sqlite")
    set_store_mode(tmp_path, "sqlite")
    repository = open_messages(tmp_path, "sqlite")
    repository.append(NewMessage("main", "runner", "info", "hello"))
    cache = InboxStoreCache(tmp_path)
    inbox = tmp_path / ".cache" / "inbox"
    signature = watched_files_signature((inbox,))

    for _ in range(8):
        cache.read()

    assert watched_files_signature((inbox,)) == signature
    assert repository.read_all().records


def test_mail_append_changes_signature_while_wal_is_open(tmp_path: Path) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-24T00:00:00Z")
    set_store_mode(tmp_path, "mirror-files")
    set_store_mode(tmp_path, "mirror-sqlite")
    set_store_mode(tmp_path, "sqlite")
    repository = open_messages(tmp_path, "sqlite")
    inbox = tmp_path / ".cache" / "inbox"
    database = inbox / "messages.sqlite3"
    with closing(sqlite3.connect(database, timeout=0.1)) as held_connection:
        held_connection.execute("BEGIN")
        held_connection.execute("SELECT * FROM messages").fetchall()
        before = watched_files_signature((inbox,))
        main_file_before = database.stat()

        repository.append(NewMessage("sender", "worker", "info", "new mail"))

        after = watched_files_signature((inbox,))
        main_file_after = database.stat()

    assert after != before
    assert (
        main_file_after.st_mtime_ns,
        main_file_after.st_size,
        main_file_after.st_ino,
    ) == (
        main_file_before.st_mtime_ns,
        main_file_before.st_size,
        main_file_before.st_ino,
    )


def test_dashboard_signature_falls_back_when_message_database_is_locked(
    tmp_path: Path,
) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-24T00:00:00Z")
    set_store_mode(tmp_path, "mirror-files")
    set_store_mode(tmp_path, "mirror-sqlite")
    set_store_mode(tmp_path, "sqlite")
    inbox = tmp_path / ".cache" / "inbox"
    database = inbox / "messages.sqlite3"
    for error in (Locked("busy"), sqlite3.OperationalError("locked"), OSError("flip")):
        with patch("varde_runner.web.cache.open_messages", side_effect=error):
            signature = watched_files_signature((inbox,))
        assert any(item[0] == str(database) for item in signature)
        assert not any(
            len(item) > 1 and item[1] == "message-version" for item in signature
        )


def test_dashboard_signature_falls_back_for_unmarked_message_database(
    tmp_path: Path,
) -> None:
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    database = inbox / "messages.sqlite3"
    with sqlite3.connect(database):
        pass

    signature = watched_files_signature((inbox,))

    assert any(item[0] == str(database) for item in signature)
    assert not any(len(item) > 1 and item[1] == "message-version" for item in signature)


def test_runner_relay_data_reads_do_not_need_runner_database(tmp_path: Path) -> None:
    _mark_import_verified(tmp_path, verified_at="2026-10-24T00:00:00Z")
    set_store_mode(tmp_path, "mirror-files")
    set_store_mode(tmp_path, "mirror-sqlite")
    set_store_mode(tmp_path, "sqlite")
    repository = open_messages(tmp_path, "sqlite")
    message = repository.append(NewMessage("sender", "worker", "info", "relay mail"))
    assert message.id is not None

    class RelayCLI:
        def __init__(self) -> None:
            self.confirmed: list[tuple[str, str, str]] = []
            self.wait_count = 0

        async def wait(self, _identity: str) -> dict[str, object]:
            self.wait_count += 1
            records = repository.read_all().records
            return {
                "actions": [
                    {
                        "action_id": "delivery-1",
                        "wake": {"agent_id": "agent-worker"},
                        "prompt": records[0].text,
                        "message_ids": [message.id],
                    }
                ]
            }

        async def renew(self, _action_id: str) -> dict[str, str]:
            return {"status": "renewed"}

        async def confirm(
            self,
            action_id: str,
            result: str,
            evidence: str,
            _identity: str,
            *,
            harness: str,
        ) -> None:
            self.confirmed.append((action_id, result, evidence))

    class WakeStore:
        def __init__(self) -> None:
            self.waits: dict[str, dict[str, object]] = {}
            self.rearmed: list[str] = []

        def create_wait(
            self,
            wait_id: str,
            _session: str,
            _kind: str,
            _deadline: str | None,
            payload: dict[str, object],
        ) -> None:
            self.waits[wait_id] = {"state": "pending", "payload": payload}

        def rearm_wake(self, wait_id: str) -> None:
            self.rearmed.append(wait_id)

        def get_wait(self, wait_id: str) -> dict[str, object] | None:
            return self.waits.get(wait_id)

        def pushed_wake_message_ids(self, _message_ids: set[str]) -> set[str]:
            return set()

        def resolve_wait(self, wait_id: str, _state: str, decision: str) -> None:
            self.waits[wait_id].update(state="resolved", decision=decision)

    class Supervisor:
        def __init__(self) -> None:
            self.store = WakeStore()
            self.sent: list[tuple[str, str, str | None, str]] = []

        async def target_idle_status(
            self, _agent_id: str, _harness: str | None = None
        ) -> str:
            return "idle"

        async def send(
            self,
            agent_id: str,
            prompt: str,
            harness: str | None = None,
            *,
            request_id: str,
        ) -> SendOutcome:
            self.sent.append((agent_id, prompt, harness, request_id))
            touch_relay_wake(tmp_path)
            return SendOutcome.SENT

    async def poll_and_deliver() -> tuple[RelayCLI, Supervisor]:
        cli, supervisor = RelayCLI(), Supervisor()
        worker = RelayWorker(cast("RelayCLIProtocol", cli), supervisor)
        worker.identity = "relay-identity"
        response = await cli.wait(worker.identity)
        await worker._process_response(response)
        return cli, supervisor

    cli, supervisor = asyncio.run(poll_and_deliver())

    assert cli.wait_count == 1
    assert cli.confirmed == [("delivery-1", "pushed", "successful-send")]
    assert supervisor.sent == [("agent-worker", "relay mail", None, "delivery-1")]
    assert supervisor.store.rearmed == ["wake:delivery-1"]
    assert supervisor.store.waits["wake:delivery-1"]["decision"] == "pushed"
    assert (tmp_path / ".cache" / "inbox" / "relay" / "relay.wake").is_file()
    assert not (tmp_path / ".cache" / "runner" / "runner.sqlite3").exists()

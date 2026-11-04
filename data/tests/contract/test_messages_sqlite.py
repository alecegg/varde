from __future__ import annotations

import json
import multiprocessing
from pathlib import Path
from typing import Any

from messages_backends import AliasResolver
from sqlite_messages import factory
from varde_data.records.messages import Delivery, Message, NewMessage, RelayEvent
from varde_data.version import Cursor


def _claim_worker(path: str, barrier: Any, output: Any) -> None:
    repository = factory(Path(path), AliasResolver())
    barrier.wait()
    output.put(
        tuple(
            message.id
            for message in repository.claim_unread("slot-a", "worker", "test")
        )
    )


def _append_worker(path: str, worker: int, count: int, barrier: Any) -> None:
    repository = factory(Path(path), AliasResolver())
    barrier.wait()
    for index in range(count):
        repository.append(
            NewMessage(
                "sender",
                "alias-a",
                "info",
                f"worker {worker} message {index}",
                ts="2026-01-01T00:00:00Z",
            )
        )


def _relay_worker(path: str, barrier: Any, output: Any) -> None:
    repository = factory(Path(path), AliasResolver())
    barrier.wait()
    event = RelayEvent(
        "m-deadbeef",
        "alias-a",
        "pushed",
        "now",
        action_created_at="action-1",
    )
    output.put(repository.record_relay_event(event).value)


def test_import_log_preserves_parsed_rows_and_legacy_id(tmp_path: Path) -> None:
    raw_path = tmp_path / "legacy.jsonl"
    raw_row = {
        "ts": "2026-01-01T00:00:00Z",
        "from": "sender",
        "to": "alias-a",
        "kind": "info",
        "text": "legacy row",
    }
    raw_path.write_text(json.dumps(raw_row, separators=(",", ":")) + "\n")
    repository = factory(tmp_path / "db", AliasResolver())

    imported = repository.import_log(raw_path)

    assert len(imported) == 1
    assert imported[0].id == imported[0].legacy_id
    assert repository.read_all().records == imported
    assert repository.peek_unread("slot-a") == imported
    assert repository.import_log(raw_path) == ()


def test_concurrent_claims_are_exclusive(tmp_path: Path) -> None:
    repository = factory(tmp_path / "db", AliasResolver())
    messages = tuple(
        repository.append(
            NewMessage(
                "sender",
                "alias-a",
                "info",
                f"message {index}",
                ts="2026-01-01T00:00:00Z",
            )
        )
        for index in range(12)
    )
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(4)
    output = context.Queue()
    processes = [
        context.Process(
            target=_claim_worker, args=(str(tmp_path / "db"), barrier, output)
        )
        for _ in range(4)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert not process.is_alive(), "claim worker did not finish"
        assert process.exitcode == 0

    claimed = [
        str(message_id) for _ in processes for message_id in output.get(timeout=5)
    ]
    expected = [str(message.id) for message in messages]
    assert sorted(claimed) == sorted(expected)
    assert len(claimed) == len(set(claimed))
    assert len(repository.deliveries()) == 2 * len(messages)


def test_concurrent_appends_preserve_every_version_bump(tmp_path: Path) -> None:
    repository = factory(tmp_path / "db", AliasResolver())
    initial_version = repository.version().value
    assert isinstance(initial_version, int)
    process_count = 4
    appends_per_process = 5
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(process_count)
    processes = [
        context.Process(
            target=_append_worker,
            args=(str(tmp_path / "db"), worker, appends_per_process, barrier),
        )
        for worker in range(process_count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert not process.is_alive(), "append worker did not finish"
        assert process.exitcode == 0

    assert (
        repository.version().value
        == initial_version + process_count * appends_per_process
    )
    assert len(repository.read_all().records) == process_count * appends_per_process


def test_concurrent_relay_duplicates_are_serialized(tmp_path: Path) -> None:
    repository = factory(tmp_path / "db", AliasResolver())
    process_count = 4
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(process_count)
    output = context.Queue()
    processes = [
        context.Process(
            target=_relay_worker,
            args=(str(tmp_path / "db"), barrier, output),
        )
        for _ in range(process_count)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert not process.is_alive(), "relay worker did not finish"
        assert process.exitcode == 0

    outcomes = [output.get(timeout=5) for _ in processes]
    assert outcomes.count("recorded") == 1
    assert outcomes.count("duplicate") == process_count - 1
    assert len(repository.deliveries()) == 1


def test_import_seeds_reader_and_empty_claim_does_not_write(
    tmp_path: Path,
) -> None:
    repository = factory(tmp_path / "db", AliasResolver())
    first = Message(
        "2026-01-01T00:00:00Z",
        "sender",
        "solo",
        "info",
        "old",
        id="m-abcdef01",
    )
    repository.import_messages((first,))
    before_empty_seed = repository.version()
    assert repository.claim_unread("unused-reader", "s", "test") == ()
    assert repository.version() != before_empty_seed

    before_seed = repository.version()
    repository.unread("solo")
    assert repository.version() == before_seed
    repository.commit_cursor("solo", Cursor("0"))

    assert (
        repository.record_delivery(
            Delivery(first.id or "", "solo", "s", "test", "delivered", "t")
        ).value
        == "recorded"
    )
    before_empty_claim = repository.version()
    assert repository.claim_unread("solo", "s", "test") == ()
    assert repository.version() == before_empty_claim
    second = repository.append(
        NewMessage("sender", "solo", "info", "new", ts="2026-01-01T00:00:00Z")
    )
    assert repository.claim_unread("solo", "s", "test") == (second,)

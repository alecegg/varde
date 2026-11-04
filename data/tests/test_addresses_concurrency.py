from __future__ import annotations

import json
import multiprocessing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.backends.files.addresses import open_addresses
from varde_data.records.addresses import ReaderContext

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _redeem(working: str, marker: str, session: str, queue: Any) -> None:
    repository = open_addresses(Path(working))
    queue.put(repository.redeem(marker, session, "h", ReaderContext(), now=NOW))


def _issue_supersede(working: str, barrier: Any, queue: Any) -> None:
    repository = open_addresses(Path(working))
    barrier.wait(10)
    queue.put(("issued", repository.issue("reader", supersede=True, now=NOW)))


def _redeem_racing_issue(working: str, marker: str, barrier: Any, queue: Any) -> None:
    repository = open_addresses(Path(working))
    barrier.wait(10)
    queue.put(
        (
            "redeemed",
            repository.redeem(
                marker, "replacement-session", "h", ReaderContext(), now=NOW
            ),
        )
    )


def _change_alias(
    working: str, operation: str, index: int, barrier: Any, queue: Any
) -> None:
    repository = open_addresses(Path(working))
    barrier.wait(10)
    if operation == "remove":
        repository.remove_alias("remove-me")
        repository.unbind("alias-session", NOW)
    else:
        repository.add_alias("slot", f"a{index}")
    queue.put(True)


def test_concurrent_redeem_has_one_binding_and_complete_events(tmp_path: Path) -> None:
    repository = open_addresses(tmp_path)
    marker = repository.issue("reader", now=NOW)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    workers = 10
    processes = [
        context.Process(target=_redeem, args=(str(tmp_path), marker, f"s{i}", queue))
        for i in range(workers)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0

    results = [queue.get(timeout=2) for _ in processes]
    assert sum(results) == 1
    raw = (tmp_path / ".cache/inbox/events.jsonl").read_bytes()
    assert raw.endswith(b"\n")
    rows = [json.loads(line) for line in raw.splitlines()]
    assert len(rows) == workers
    assert sum(row["event"] == "bind" for row in rows) == 1
    assert len(repository.list_bindings()) == 1


def test_concurrent_supersede_issue_and_redeem_are_serialized(tmp_path: Path) -> None:
    repository = open_addresses(tmp_path)
    original = repository.issue("reader", now=NOW)
    assert repository.redeem(
        original, "original-session", "h", ReaderContext(), now=NOW
    )
    replacement = repository.issue("reader", supersede=True, now=NOW)

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    queue = context.Queue()
    workers = [
        context.Process(target=_issue_supersede, args=(str(tmp_path), barrier, queue)),
        context.Process(
            target=_redeem_racing_issue,
            args=(str(tmp_path), replacement, barrier, queue),
        ),
    ]
    for process in workers:
        process.start()
    for process in workers:
        process.join(30)
        assert process.exitcode == 0

    results = dict(queue.get(timeout=2) for _ in workers)
    issued, redeemed = results["issued"], results["redeemed"]
    assert issued.startswith("[varde-address: reader ")
    assert redeemed is True
    assert repository.current_binding("reader") is not None
    assert len((tmp_path / ".cache/inbox/events.jsonl").read_bytes().splitlines()) == 3


def test_concurrent_slot_add_and_remove_preserve_all_additions(tmp_path: Path) -> None:
    repository = open_addresses(tmp_path)
    repository.add_alias("slot", "remove-me")
    marker = repository.issue("alias-worker", now=NOW)
    assert repository.redeem(marker, "alias-session", "h", ReaderContext(), now=NOW)
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(9)
    queue = context.Queue()
    processes = [
        context.Process(
            target=_change_alias,
            args=(str(tmp_path), "add", index, barrier, queue),
        )
        for index in range(8)
    ]
    processes.append(
        context.Process(
            target=_change_alias,
            args=(str(tmp_path), "remove", 8, barrier, queue),
        )
    )
    for process in processes:
        process.start()
    for process in processes:
        process.join(30)
        assert process.exitcode == 0

    assert all(queue.get(timeout=2) for _ in processes)
    assert repository.reader_addresses("slot") == {"slot", *(f"a{i}" for i in range(8))}
    raw_events = (tmp_path / ".cache/inbox/events.jsonl").read_bytes()
    assert raw_events.endswith(b"\n")
    assert len(raw_events.splitlines()) == 2

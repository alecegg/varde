from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import sys
import threading
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest
from varde_workflow.commands.msg import (
    append_message,
    claim_unread,
    delivery_events,
    record_delivery,
    unread,
)


def test_delivered_messages_are_not_unread_and_first_delivery_wins(
    tmp_path: Path,
) -> None:
    message = append_message("sender", "reader", "info", "hello", working=tmp_path)
    assert message.id is not None
    assert [item.id for item in unread(tmp_path, "reader")] == [message.id]
    record_delivery(tmp_path, message.id, "reader", now="2026-01-01T00:00:01Z")
    record_delivery(tmp_path, message.id, "reader", now="2026-01-01T00:00:02Z")
    assert unread(tmp_path, "reader") == []
    assert (
        sum(event["event"] == "delivered" for event in delivery_events(tmp_path)) == 1
    )


def test_misdelivered_event_does_not_mark_message_delivered(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from varde_workflow.inbox import record_relay_event

    message = append_message("sender", "reader", "info", "hello", working=tmp_path)
    assert record_relay_event(
        tmp_path,
        message.id or "",
        "reader",
        "misdelivered",
        now=datetime(2026, 1, 1, tzinfo=UTC),
        expected_address="reader",
        actual_address="other",
    )
    assert unread(tmp_path, "reader") == [message]


def _claim(args: tuple[str, str]) -> list[str]:
    messages = claim_unread(
        args[0], "reader", args[1], "cli", now="2026-01-01T00:00:00Z"
    )
    return [message.id or "" for message in messages]


def test_concurrent_claims_return_each_message_once(tmp_path: Path) -> None:
    messages = [
        append_message("sender", "reader", "info", str(i), working=tmp_path)
        for i in range(4)
    ]
    try:
        multiprocessing.Semaphore(1)
        pool = ProcessPoolExecutor(max_workers=2)
    except OSError as error:
        pytest.skip(f"process pools are unavailable: {error}")
    with pool:
        results = list(
            pool.map(_claim, [(str(tmp_path), "one"), (str(tmp_path), "two")])
        )
    assert sorted(message_id for result in results for message_id in result) == sorted(
        message.id or "" for message in messages
    )


def test_concurrent_claims_skip_when_pool_creation_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable_pool(*, max_workers: int) -> ProcessPoolExecutor:
        raise PermissionError("semaphores are unavailable")

    monkeypatch.setattr(sys.modules[__name__], "ProcessPoolExecutor", unavailable_pool)

    with pytest.raises(pytest.skip.Exception, match="process pools are unavailable"):
        test_concurrent_claims_return_each_message_once(tmp_path)


def test_legacy_message_identity_uses_byte_offset_and_line(tmp_path: Path) -> None:
    path = tmp_path / ".cache" / "inbox" / "messages.jsonl"
    path.parent.mkdir(parents=True)
    line = (
        json.dumps(
            {
                "ts": "now",
                "from": "sender",
                "to": "reader",
                "kind": "info",
                "text": "legacy",
            }
        )
        + "\n"
    )
    path.write_text(line)
    (path.parent / "cursors").mkdir()
    (path.parent / "cursors" / "reader").write_text("0")
    first = unread(tmp_path, "reader")[0].id
    assert first is not None
    # The same line at the same byte offset keeps its identity across reads.
    assert unread(tmp_path, "reader")[0].id == first
    # A skipped prefix shifts the offset, so the identity changes.
    path.write_text("{invalid json}\n" + line)
    prefixed = unread(tmp_path, "reader")[0].id
    assert prefixed is not None
    assert prefixed != first


def test_unread_skips_large_invalid_prefix_below_watermark(tmp_path: Path) -> None:
    path = tmp_path / ".cache" / "inbox" / "messages.jsonl"
    path.parent.mkdir(parents=True)
    prefix = "{invalid json}\n" * 10_000
    path.write_text(
        prefix
        + json.dumps(
            {
                "ts": "now",
                "from": "sender",
                "to": "reader",
                "kind": "info",
                "text": "new",
                "id": "m-12345678",
            }
        )
        + "\n"
    )
    (path.parent / "index").mkdir()
    (path.parent / "index" / "reader.json").write_text(
        json.dumps({"watermark": len(prefix.encode())})
    )
    assert [message.text for message in unread(tmp_path, "reader")] == ["new"]


def test_first_delivery_preserves_existing_cursor_history(tmp_path: Path) -> None:
    from varde_workflow.inbox import Message

    path = tmp_path / ".cache" / "inbox" / "messages.jsonl"
    path.parent.mkdir(parents=True)
    old = Message("now", "sender", "reader", "info", "old", id="m-87654321")
    path.write_text(old.to_json() + "\n")
    offset = path.stat().st_size
    (path.parent / "cursors").mkdir()
    (path.parent / "cursors" / "reader").write_text(str(offset))
    record_delivery(tmp_path, old.id or "", "reader", "delivered")
    assert unread(tmp_path, "reader") == []


def test_hook_delivery_and_relay_confirmation_do_not_deadlock(tmp_path: Path) -> None:
    from varde_workflow.relay_state import confirm, lease_actions

    now = datetime(2026, 1, 1, tzinfo=UTC)
    message = append_message(
        "sender", "reader", "blocked", "hello", working=tmp_path, now=now
    )
    action = lease_actions(
        tmp_path,
        [{"address": "reader", "message_ids": [message.id]}],
        "mailman",
        now,
        harness="claude",
    )[0]
    barrier = threading.Barrier(2)

    def hook() -> None:
        barrier.wait()
        record_delivery(
            tmp_path, message.id or "", "reader", via="hook", now=now.isoformat()
        )

    def relay() -> None:
        barrier.wait()
        confirm(tmp_path, action["action_id"], "pushed", now)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(hook), pool.submit(relay)]
        for future in futures:
            future.result(timeout=2)
    assert (
        sum(event["event"] == "delivered" for event in delivery_events(tmp_path)) == 1
    )


def test_watermark_stops_at_first_undelivered_reader_message(tmp_path: Path) -> None:
    first = append_message("sender", "reader", "info", "first", working=tmp_path)
    second = append_message("sender", "reader", "info", "second", working=tmp_path)
    record_delivery(tmp_path, second.id or "", "reader", "delivered")
    index = tmp_path / ".cache" / "inbox" / "index" / "reader.json"
    assert json.loads(index.read_text())["watermark"] == 0
    assert [message.id for message in unread(tmp_path, "reader")] == [first.id]


def test_cursor_never_moves_backwards(tmp_path: Path) -> None:
    from varde_workflow.commands.msg import commit_cursor

    append_message("sender", "reader", "info", "one", working=tmp_path)
    append_message("sender", "reader", "info", "two", working=tmp_path)
    end = (tmp_path / ".cache" / "inbox" / "messages.jsonl").stat().st_size
    commit_cursor(tmp_path, "reader", end)
    commit_cursor(tmp_path, "reader", 0)
    assert (tmp_path / ".cache" / "inbox" / "cursors" / "reader").read_text() == str(
        end
    )


def test_ack_requires_valid_id_and_prior_delivery_to_reader(tmp_path: Path) -> None:
    message = append_message("sender", "reader", "info", "hello", working=tmp_path)
    with pytest.raises(ValueError, match="does not exist"):
        record_delivery(tmp_path, "m-00000000", "reader", "acked")
    with pytest.raises(ValueError, match="delivered"):
        record_delivery(tmp_path, message.id or "", "reader", "acked")
    record_delivery(tmp_path, message.id or "", "other")
    with pytest.raises(ValueError, match="delivered"):
        record_delivery(tmp_path, message.id or "", "reader", "acked")
    assert unread(tmp_path, "reader") == [message]
    record_delivery(tmp_path, message.id or "", "reader")
    record_delivery(tmp_path, message.id or "", "reader", "acked")


def test_cli_ack_rejects_an_invalid_id_with_exit_one(capsys) -> None:
    from varde_workflow import cli

    assert cli.run(["msg", "ack", "--as", "reader", "unknown"]) == 1
    assert "Error: message id must match" in capsys.readouterr().err


def test_cli_claim_json_exposes_message_id_and_cli_via(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    import json
    from types import SimpleNamespace

    from varde_learn.knowledge import memory
    from varde_workflow import cli

    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    message = append_message("sender", "main", "info", "hello", working=tmp_path)
    assert cli.run(["msg", "read", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["data"]["messages"][0]["id"] == message.id
    events = delivery_events(tmp_path)
    assert events[0]["via"] == "cli"
    assert events[0]["message_id"] == message.id

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest


def test_hook_helpers_import_without_workflow_dependencies() -> None:
    check = (
        "import sys; from varde_workflow import inbox; "
        "assert inbox.SETUP_WARNING.startswith('Varde will not work as designed'); "
        "assert not any(name in sys.modules for name in "
        "('yaml', 'varde_workflow.artifact', 'varde_learn.knowledge.frontmatter', "
        "'varde_learn.knowledge.memory'))"
    )
    subprocess.run(  # noqa: S603 - Isolated import test executes a fixed assertion snippet in the current interpreter.
        [sys.executable, "-c", check], check=True
    )


def test_inbox_returns_only_new_messages_across_reads(tmp_path: Path) -> None:
    from varde_workflow.commands.msg import (
        append_message,
        claim_unread,
        commit_cursor,
        read_all,
        read_unread,
    )

    append_message("worker", "main", "info", "hello", working=tmp_path)
    first = claim_unread(tmp_path, "main", "session", "cli")

    assert [message.text for message in first] == ["hello"]
    assert read_all(tmp_path)[0].line() == "worker info: hello"
    commit_cursor(tmp_path, "main", 0)
    assert claim_unread(tmp_path, "main", "session", "cli") == []

    append_message("builder", "main", "done", "finished", working=tmp_path)
    newest, new_offset = read_unread(tmp_path, "main")

    assert [message.text for message in newest] == ["finished"]
    assert new_offset is not None


def test_message_json_omits_absent_notes(tmp_path: Path) -> None:
    from varde_workflow.inbox import Message

    message = Message("ts", "a", "b", "info", "hello")
    assert json.loads(message.to_json()) == {
        "ts": "ts",
        "from": "a",
        "to": "b",
        "kind": "info",
        "text": "hello",
    }


def test_append_message_is_owned_by_inbox_and_pending_view_covers_each_reader(
    tmp_path: Path,
) -> None:
    from varde_workflow import inbox
    from varde_workflow.commands.msg import append_message

    assert append_message is inbox.append_message
    one = append_message("sender", "one", "info", "first", working=tmp_path)
    two = append_message("sender", "two", "info", "second", working=tmp_path)
    assert {
        address: [message.id for message in messages]
        for address, messages in inbox.pending_for_readers(tmp_path).items()
    } == {"one": [one.id], "two": [two.id]}


def test_append_message_accepts_info_failure(tmp_path: Path) -> None:
    from varde_workflow.inbox import append_message

    message = append_message(
        "varde-runner",
        "main",
        "info-failure",
        "Daily learn sweep failed",
        working=tmp_path,
    )

    assert message.kind == "info-failure"


def test_has_managed_block_requires_a_matching_end_marker(tmp_path: Path) -> None:
    from varde_workflow.inbox import has_managed_block

    path = tmp_path / "instructions.md"
    path.write_bytes(b"<!-- varde:start -->\ncontent\n<!-- varde:end -->")
    assert has_managed_block(path)
    path.write_bytes(b"<!-- varde:start -->\ncontent")
    assert not has_managed_block(path)
    path.write_bytes(b"<!-- varde:end -->")
    assert not has_managed_block(path)


def test_pending_view_keeps_escalated_messages_pending_and_append_errors_are_stable(
    tmp_path: Path,
) -> None:
    from varde_workflow.inbox import (
        append_message,
        pending_for_readers,
        record_relay_event,
    )

    message = append_message("sender", "reader", "info", "hello", working=tmp_path)
    assert message.id is not None
    record_relay_event(
        tmp_path, message.id, "reader", "escalated", now=datetime.now(UTC)
    )
    assert pending_for_readers(tmp_path)["reader"] == [message]
    with pytest.raises(ValueError, match="must not be empty"):
        append_message("sender", "reader", "info", "", working=tmp_path)
    with pytest.raises(ValueError, match="use --notes <path>"):
        append_message("sender", "reader", "info", "x" * 301, working=tmp_path)


def test_failed_relay_events_do_not_hide_hook_mail(tmp_path: Path) -> None:
    from varde_workflow.commands.msg import append_message
    from varde_workflow.inbox import claim_unread, record_relay_event

    message = append_message(
        "sender", "main", "needs-user", "still here", working=tmp_path
    )
    for index in range(3):
        record_relay_event(
            tmp_path,
            message.id or "",
            "main",
            "failed",
            now=datetime(2026, 10, 18, 12, index, tzinfo=UTC),
            via="relay",
        )

    assert [
        item.text for item in claim_unread(tmp_path, "main", "session", "hook")
    ] == ["still here"]

from __future__ import annotations

from argparse import Namespace
from datetime import UTC, datetime

from varde_data.role_inbox import select_role_inbox
from varde_data.store_mode import _mark_import_verified, set_store_mode
from varde_workflow.binding import BindingStore
from varde_workflow.commands.msg import run
from varde_workflow.inbox import delivery_events
from varde_workflow.slots import add_alias

NOW = datetime.now(UTC)


def _sqlite_mode(working) -> None:
    _mark_import_verified(working, verified_at="2026-10-28T00:00:00Z")
    set_store_mode(working, "mirror-files")
    set_store_mode(working, "mirror-sqlite")
    set_store_mode(working, "sqlite")


def _send(to: str) -> Namespace:
    return Namespace(
        message_command="send",
        from_address="main",
        to=to,
        kind="info",
        text="shared mail",
        notes=None,
        reply_to=None,
        urgent=False,
    )


def test_unqualified_role_send_is_shared_to_each_live_holder(
    tmp_path, monkeypatch, capsys
) -> None:
    store = BindingStore(tmp_path)
    for plan in ("plan-a", "plan-b"):
        monkeypatch.setenv("PASEO_AGENT_ID", f"agent-{plan}")
        marker = store.issue(f"{plan}-builder", now=NOW)
        assert store.redeem(marker, f"session-{plan}", "claude", "/repo", now=NOW)
    _sqlite_mode(tmp_path)

    assert run(_send("builder"), tmp_path) == 0
    captured = capsys.readouterr()
    assert "to builder (live)" in captured.out
    inbox = select_role_inbox(tmp_path)
    assert inbox is not None
    first = inbox.unread("builder", "plan-a-builder")
    second = inbox.unread("builder", "plan-b-builder")
    assert len(first) == len(second) == 1
    assert first[0].id == second[0].id
    inbox.ack("builder", "plan-a-builder", first[0].id or "")
    assert inbox.unread("builder", "plan-a-builder") == ()
    assert [row.id for row in inbox.unread("builder", "plan-b-builder")] == [
        second[0].id
    ]


def test_files_mode_keeps_qualified_role_as_slot_mail(tmp_path, capsys) -> None:
    add_alias(tmp_path, "orchestrator-1", "plan-a")

    assert run(_send("builder:plan-a"), tmp_path) == 0

    assert (
        '"to":"plan-a-builder"'
        in (tmp_path / ".cache/inbox/messages.jsonl").read_text()
    )
    assert select_role_inbox(tmp_path) is None


def test_first_binding_reads_queued_role_message(tmp_path, monkeypatch, capsys) -> None:
    add_alias(tmp_path, "orchestrator-1", "plan-a")
    _sqlite_mode(tmp_path)
    assert run(_send("builder:plan-a"), tmp_path) == 0
    capsys.readouterr()

    monkeypatch.setenv("PASEO_AGENT_ID", "agent-first")
    store = BindingStore(tmp_path)
    marker = store.issue("plan-a-builder", now=NOW)
    assert store.redeem(marker, "first", "claude", "/repo", now=NOW)
    args = Namespace(
        message_command="read", address="plan-a-builder", all=False, json=False
    )
    assert run(args, tmp_path) == 0
    assert "shared mail" in capsys.readouterr().out


def test_role_read_records_delivery_and_ack_events(
    tmp_path, monkeypatch, capsys
) -> None:
    _sqlite_mode(tmp_path)
    store = BindingStore(tmp_path)
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-first")
    marker = store.issue("plan-a-builder", now=NOW)
    assert store.redeem(marker, "first", "claude", "/repo", now=NOW)
    assert run(_send("builder:plan-a"), tmp_path) == 0
    capsys.readouterr()

    args = Namespace(
        message_command="read", address="plan-a-builder", all=False, json=False
    )
    assert run(args, tmp_path) == 0
    capsys.readouterr()

    events = delivery_events(tmp_path)
    assert {event["event"] for event in events} >= {"delivered", "acked"}
    assert {event["reader"] for event in events} == {"plan-a-builder"}


def test_later_role_holder_does_not_replay_old_broadcast(
    tmp_path, monkeypatch, capsys
) -> None:
    _sqlite_mode(tmp_path)
    store = BindingStore(tmp_path)
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-first")
    first_marker = store.issue("plan-a-builder", now=NOW)
    assert store.redeem(first_marker, "first", "claude", "/repo", now=NOW)
    assert run(_send("builder"), tmp_path) == 0
    capsys.readouterr()

    monkeypatch.setenv("PASEO_AGENT_ID", "agent-later")
    later_marker = store.issue("plan-b-builder", now=NOW)
    assert store.redeem(later_marker, "later", "claude", "/repo", now=NOW)
    args = Namespace(
        message_command="read", address="plan-b-builder", all=False, json=False
    )

    assert run(args, tmp_path) == 0
    assert "shared mail" not in capsys.readouterr().out


def test_successor_keeps_role_cursor_for_same_slot(tmp_path, capsys) -> None:
    add_alias(tmp_path, "orchestrator-1", "plan-a")
    _sqlite_mode(tmp_path)
    store = BindingStore(tmp_path)
    old_marker = store.issue("plan-a-builder", now=NOW)
    assert store.redeem(old_marker, "old", "claude", "/repo", now=NOW)
    inbox = select_role_inbox(tmp_path)
    assert inbox is not None
    assert run(_send("builder:plan-a"), tmp_path) == 0
    assert run(_send("builder:plan-a"), tmp_path) == 0
    rows = inbox.unread("builder:plan-a", "plan-a-builder")
    assert len(rows) == 2
    inbox.ack("builder:plan-a", "plan-a-builder", rows[0].id or "")
    successor = store.issue("plan-a-builder", supersede=True, now=NOW)
    assert store.redeem(successor, "new", "claude", "/repo", now=NOW)

    assert [row.id for row in inbox.unread("builder:plan-a", "plan-a-builder")] == [
        rows[1].id
    ]
    capsys.readouterr()


def test_ack_command_advances_only_the_selected_role_holder(
    tmp_path, monkeypatch, capsys
) -> None:
    _sqlite_mode(tmp_path)
    store = BindingStore(tmp_path)
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-a")
    marker = store.issue("plan-a-builder", now=NOW)
    assert store.redeem(marker, "session-a", "claude", "/repo", now=NOW)
    assert run(_send("builder:plan-a"), tmp_path) == 0
    inbox = select_role_inbox(tmp_path)
    assert inbox is not None
    message = inbox.unread("builder:plan-a", "plan-a-builder")[0]

    ack = Namespace(
        message_command="ack",
        id=message.id,
        address="plan-a-builder",
    )
    assert run(ack, tmp_path) == 0

    assert inbox.unread("builder:plan-a", "plan-a-builder") == ()
    capsys.readouterr()

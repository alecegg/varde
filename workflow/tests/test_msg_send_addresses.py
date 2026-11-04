from __future__ import annotations

from argparse import Namespace
from datetime import UTC, datetime, timedelta

import pytest
from varde_workflow.binding import BindingStore
from varde_workflow.commands.msg import run
from varde_workflow.inbox import claim_unread
from varde_workflow.slots import add_alias

NOW = datetime.now(UTC)


def _args(to: str) -> Namespace:
    return Namespace(
        message_command="send",
        from_address="main",
        to=to,
        kind="info",
        text="hello",
        notes=None,
        reply_to=None,
    )


def test_send_resolves_paseo_agent_id_to_slot(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-uuid-123456")
    store = BindingStore(tmp_path)
    marker = store.issue("worker", now=NOW)
    assert store.redeem(marker, "session", "claude", "/repo", now=NOW)

    assert run(_args("agent-uuid-123456"), tmp_path) == 0
    assert capsys.readouterr().err
    assert '"to":"worker"' in (tmp_path / ".cache/inbox/messages.jsonl").read_text()


def test_send_resolves_short_agent_id_prefix_to_slot(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-uuid-123456")
    store = BindingStore(tmp_path)
    marker = store.issue("worker", now=NOW)
    assert store.redeem(marker, "session", "claude", "/repo", now=NOW)

    assert run(_args("agent-uuid"), tmp_path) == 0
    assert '"to":"worker"' in (tmp_path / ".cache/inbox/messages.jsonl").read_text()


def test_send_resolves_plan_id_alias_to_slot(tmp_path, capsys) -> None:
    add_alias(tmp_path, "orchestrator-2", "plan-reliable-mail")

    assert run(_args("plan-reliable-mail"), tmp_path) == 0
    assert (
        '"to":"orchestrator-2"'
        in (tmp_path / ".cache/inbox/messages.jsonl").read_text()
    )


def test_send_unknown_recipient_fails_without_queueing(tmp_path, capsys) -> None:
    add_alias(tmp_path, "orchestrator-2", "plan-reliable-mail")

    assert run(_args("no-such-agent-xyz"), tmp_path) == 1
    captured = capsys.readouterr()
    assert "unknown recipient" in captured.err
    assert "orchestrator-2" in captured.err
    assert not (tmp_path / ".cache/inbox/messages.jsonl").exists()


def test_send_resolves_qualified_role_to_live_slot(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-a")
    store = BindingStore(tmp_path)
    marker = store.issue("plan-a-builder", now=NOW)
    assert store.redeem(marker, "session-a", "claude", "/repo", now=NOW)

    assert run(_args("builder:plan-a"), tmp_path) == 0
    captured = capsys.readouterr()
    assert "to plan-a-builder (live)" in captured.out
    assert (
        '"to":"plan-a-builder"'
        in (tmp_path / ".cache/inbox/messages.jsonl").read_text()
    )


def test_send_queues_qualified_role_without_live_holder(tmp_path, capsys) -> None:
    add_alias(tmp_path, "orchestrator-1", "plan-a")
    assert run(_args("builder:plan-a"), tmp_path) == 0
    captured = capsys.readouterr()
    assert "to plan-a-builder (no-holder)" in captured.out
    assert (
        '"to":"plan-a-builder"'
        in (tmp_path / ".cache/inbox/messages.jsonl").read_text()
    )


def test_successor_binding_inherits_role_mailbox_and_unread_cursor(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-old")
    store = BindingStore(tmp_path)
    old_marker = store.issue("plan-a-builder", now=NOW)
    assert store.redeem(old_marker, "old", "claude", "/repo", now=NOW)
    assert run(_args("builder:plan-a"), tmp_path) == 0
    message = claim_unread(tmp_path, "plan-a-builder", "old", "cli")[0]
    assert message.to == "plan-a-builder"
    capsys.readouterr()

    monkeypatch.setenv("PASEO_AGENT_ID", "agent-new")
    successor_marker = store.issue("plan-a-builder", supersede=True, now=NOW)
    assert store.redeem(successor_marker, "new", "claude", "/repo", now=NOW)
    assert claim_unread(tmp_path, "plan-a-builder", "new", "cli") == []


def test_send_unqualified_role_lists_multiple_live_qualifiers(
    tmp_path, monkeypatch, capsys
) -> None:
    store = BindingStore(tmp_path)
    for plan in ("plan-a", "plan-b"):
        monkeypatch.setenv("PASEO_AGENT_ID", f"agent-{plan}")
        marker = store.issue(f"{plan}-builder", now=NOW)
        assert store.redeem(marker, f"session-{plan}", "claude", "/repo", now=NOW)

    assert run(_args("builder"), tmp_path) == 1
    error = capsys.readouterr().err
    assert "ambiguous role" in error
    assert "plan-a, plan-b" in error
    assert not (tmp_path / ".cache/inbox/messages.jsonl").exists()


def test_send_unqualified_role_lists_multiple_non_live_qualifiers(
    tmp_path, monkeypatch, capsys
) -> None:
    store = BindingStore(tmp_path)
    stale = NOW - timedelta(hours=1)
    for plan in ("plan-a", "plan-b"):
        monkeypatch.setenv("PASEO_AGENT_ID", f"agent-{plan}")
        marker = store.issue(f"{plan}-builder", now=stale)
        assert store.redeem(marker, f"session-{plan}", "claude", "/repo", now=stale)

    assert run(_args("builder"), tmp_path) == 1
    assert "plan-a, plan-b" in capsys.readouterr().err
    assert not (tmp_path / ".cache/inbox/messages.jsonl").exists()


def test_unknown_role_qualifier_fails_with_nearest_candidates(tmp_path, capsys) -> None:
    add_alias(tmp_path, "orchestrator-1", "plan-mail")

    assert run(_args("builder:plan-typo"), tmp_path) == 1
    error = capsys.readouterr().err
    assert "unknown role qualifier" in error
    assert "plan-mail" in error
    assert not (tmp_path / ".cache/inbox/messages.jsonl").exists()


@pytest.mark.parametrize("name", ["agent-", "plan-mai"])
def test_prefix_lookup_requires_agent_id_of_at_least_eight_chars(
    name, tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-uuid-123456")
    store = BindingStore(tmp_path)
    marker = store.issue("worker", now=NOW)
    assert store.redeem(marker, "session", "claude", "/repo", now=NOW)
    add_alias(tmp_path, "orchestrator-2", "plan-mail")

    assert run(_args(name), tmp_path) == 1
    assert "unknown recipient" in capsys.readouterr().err


def test_main_role_send_reports_queued_state(tmp_path, capsys) -> None:
    assert run(_args("manager"), tmp_path) == 0
    output = capsys.readouterr().out
    assert output.startswith("sent m-")
    assert "to main (queued)" in output

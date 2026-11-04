from __future__ import annotations

from argparse import Namespace
from datetime import UTC, datetime, timedelta

from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.store_mode import _mark_import_verified, set_store_mode
from varde_runner.relay import DataRelay
from varde_workflow.binding import BindingStore
from varde_workflow.commands.msg import run as run_msg
from varde_workflow.slots import add_alias

NOW = datetime.now(UTC)


def _sqlite_mode(working) -> None:
    _mark_import_verified(working, verified_at="2026-10-28T00:00:00Z")
    set_store_mode(working, "mirror-files")
    set_store_mode(working, "mirror-sqlite")
    set_store_mode(working, "sqlite")


def _send_role(working, role: str, text: str = "relay mail") -> int:
    return run_msg(
        Namespace(
            message_command="send",
            from_address="main",
            to=role,
            kind="blocked",
            text=text,
            notes=None,
            reply_to=None,
            urgent=False,
        ),
        working,
    )


def test_relay_expands_one_role_message_to_each_live_holder(
    tmp_path, monkeypatch
) -> None:
    _sqlite_mode(tmp_path)
    store = BindingStore(tmp_path)
    for plan in ("plan-a", "plan-b"):
        monkeypatch.setenv("PASEO_AGENT_ID", f"agent-{plan}")
        marker = store.issue(f"{plan}-builder", now=NOW)
        assert store.redeem(marker, f"session-{plan}", "claude", "/repo", now=NOW)

    assert _send_role(tmp_path, "builder") == 0
    relay = DataRelay(tmp_path, now=lambda: NOW)
    state = relay.service._state()

    assert {row["to"] for row in state["messages"]} == {
        "plan-a-builder",
        "plan-b-builder",
    }
    assert len(open_data(tmp_path, load_data_config()).messages.read_all().records) == 1

    sent_at = datetime.now(UTC)
    first = relay.service.once("relay-1", now=sent_at + timedelta(seconds=1))
    assert len(first["actions"]) == 1
    first_action = first["actions"][0]
    assert (
        relay.service.confirm(
            first_action["action_id"],
            "pushed",
            now=sent_at + timedelta(seconds=2),
            harness="claude",
        )["status"]
        == "confirmed"
    )
    second = relay.service.once("relay-1", now=sent_at + timedelta(seconds=3))
    assert len(second["actions"]) == 1, second
    assert second["actions"][0]["address"] != first_action["address"]


def test_no_holder_role_mail_remains_queued_and_escalates(tmp_path) -> None:
    add_alias(tmp_path, "orchestrator-1", "plan-a")
    _sqlite_mode(tmp_path)
    assert _send_role(tmp_path, "builder:plan-a") == 0
    messages = open_data(tmp_path, load_data_config()).messages.read_all().records
    role_message = next(row for row in messages if row.to == "builder:plan-a")
    relay = DataRelay(tmp_path, now=lambda: NOW)

    assert role_message.to == "builder:plan-a"
    assert role_message.id in relay.service.escalate_due(NOW + timedelta(minutes=20))

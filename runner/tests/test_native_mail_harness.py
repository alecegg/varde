from __future__ import annotations

import asyncio
from argparse import Namespace
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import cast

import pytest
from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.records.addresses import ReaderContext
from varde_runner.relay import RelayCLIProtocol, RelayWorker
from varde_runner.supervisor import SendOutcome
from varde_workflow.commands import msg
from varde_workflow.relay_wait import once
from varde_workflow.slots import add_alias

ADAPTERS = ("claude-cli", "codex-app-server", "pi-rpc", "opencode-http")


class FakeRelayCommand:
    async def renew(self, action_id: str) -> dict[str, str]:
        return {"status": "renewed"}


class FakeSupervisorTransport:
    def __init__(self, status: str = "idle", send_error: Exception | None = None):
        self.status = status
        self.send_error = send_error
        self.status_calls: list[tuple[str, str | None]] = []
        self.send_calls: list[tuple[str, str, str | None, str | None]] = []

    async def target_idle_status(self, agent_id: str, harness: str | None) -> str:
        self.status_calls.append((agent_id, harness))
        return self.status

    async def send(
        self,
        agent_id: str,
        prompt: str,
        harness: str | None,
        *,
        request_id: str | None = None,
    ) -> SendOutcome:
        self.send_calls.append((agent_id, prompt, harness, request_id))
        if self.send_error:
            raise self.send_error
        return SendOutcome.SENT


def _send_cli_message(working: Path) -> None:
    add_alias(working, "recipient")
    args = Namespace(
        message_command="send",
        from_address="varde-builder",
        to="recipient",
        kind="info",
        text="please review this change",
        notes=None,
        reply_to=None,
    )
    assert msg.run(args, working) == 0


def _relay_action(working: Path, harness: str, now: datetime) -> dict:
    data = open_data(working, load_data_config())
    addresses = data.addresses
    recipient_marker = addresses.issue("recipient", now=now, issuer="test")
    assert addresses.redeem(
        recipient_marker,
        "agent-1",
        harness,
        ReaderContext(cwd=str(working), agent_id="agent-1", runner_harness=harness),
        now=now,
    )
    mailman_marker = addresses.issue("mailman", now=now, issuer="test")
    assert addresses.redeem(
        mailman_marker,
        "runner-mailman",
        "codex",
        ReaderContext(cwd=str(working)),
        now=now,
    )
    token = addresses.current_token("mailman")
    assert token
    response = once(working, token, now + timedelta(minutes=3))
    return response["actions"][0]


def _read_through_command(working: Path) -> str:
    args = Namespace(message_command="read", address="recipient", all=False, json=False)
    output = StringIO()
    with redirect_stdout(output):
        assert msg.run(args, working) == 0
    return output.getvalue()


@pytest.mark.parametrize("harness", ADAPTERS)
def test_native_adapter_mail_send_wake_and_consume_without_paseo_prompt(
    tmp_path: Path, harness: str
) -> None:
    working = tmp_path / "working"
    _send_cli_message(working)
    action = _relay_action(working, harness, datetime.now(UTC))
    transport = FakeSupervisorTransport()
    relay = RelayWorker(cast("RelayCLIProtocol", FakeRelayCommand()), transport)

    outcome = asyncio.run(relay.deliver(action))
    received = _read_through_command(working)

    assert outcome == ("pushed", "successful-send")
    assert transport.status_calls == [("agent-1", harness)]
    assert transport.send_calls == [
        ("agent-1", action["prompt"], harness, action["action_id"])
    ]
    assert action["wake"]["agent_id"] == "agent-1"
    assert action["prompt"].splitlines()[0] == (
        f"[varde-delivery: {action['action_id']} recipient]"
    )
    assert (
        action["prompt"].splitlines()[1].startswith("Varde messages for recipient: m-")
    )
    assert "varde-builder" in received
    assert "please review this change" in received


@pytest.mark.parametrize("harness", ADAPTERS)
def test_native_adapter_busy_mail_is_skipped_and_remains_unread(
    tmp_path: Path, harness: str
) -> None:
    working = tmp_path / "working"
    _send_cli_message(working)
    action = _relay_action(working, harness, datetime.now(UTC))
    transport = FakeSupervisorTransport(status="running")
    relay = RelayWorker(cast("RelayCLIProtocol", FakeRelayCommand()), transport)

    outcome = asyncio.run(relay.deliver(action))

    assert outcome == ("skipped-busy", "observed-result")
    assert transport.status_calls == [("agent-1", harness)]
    assert transport.send_calls == []
    assert "please review this change" in _read_through_command(working)


@pytest.mark.parametrize("harness", ADAPTERS)
def test_native_adapter_send_failure_is_failed_and_mail_remains_unread(
    tmp_path: Path, harness: str
) -> None:
    working = tmp_path / "working"
    _send_cli_message(working)
    action = _relay_action(working, harness, datetime.now(UTC))
    transport = FakeSupervisorTransport(send_error=RuntimeError("provider offline"))
    relay = RelayWorker(cast("RelayCLIProtocol", FakeRelayCommand()), transport)

    outcome = asyncio.run(relay.deliver(action))

    assert outcome == ("failed", "observed-result")
    assert transport.status_calls == [("agent-1", harness)]
    assert len(transport.send_calls) == 1
    assert "please review this change" in _read_through_command(working)

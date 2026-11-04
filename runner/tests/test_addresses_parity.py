from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde_data.config import DataConfig
from varde_data.open import open_data
from varde_data.records.addresses import ReaderContext
from varde_data.records.messages import NewMessage
from varde_data.relay import RelayService
from varde_data.service import AddressService
from varde_runner.varde_cli import VardeCLI


def test_runner_address_bindings_include_alias_bindings(tmp_path: Path):
    working = tmp_path / "working"
    data = open_data(working, DataConfig())
    AddressService(data.addresses, data.messages).add_alias("plan", "plan-next")
    marker = data.addresses.issue("plan", now=datetime.now(UTC))
    assert data.addresses.redeem(
        marker, "plan-session", "codex", ReaderContext(), now=datetime.now(UTC)
    )

    bindings = VardeCLI(
        cwd=tmp_path, env={"VARDE_WORKING_DIR": str(working)}
    ).read_address_bindings()

    assert [row["address"] for row in bindings] == ["plan"]
    assert data.addresses.resolve_alias("plan-next") == "plan"


def test_data_relay_restart_between_lease_and_confirm(tmp_path: Path):
    working = tmp_path / "working"
    now = datetime(2026, 10, 22, 12, tzinfo=UTC)
    data = open_data(working, DataConfig())
    marker = data.addresses.issue("reader", now=now)
    assert data.addresses.redeem(
        marker, "reader-session", "codex", ReaderContext(), now=now
    )
    data.messages.append(
        NewMessage(
            "sender",
            "reader",
            "info",
            "due",
            ts=(now - timedelta(minutes=3)).isoformat(),
        )
    )
    first = RelayService(data.addresses, data.messages, now=lambda: now)
    response = first.once("mailman-token")
    action_id = response["actions"][0]["action_id"]

    reopened = open_data(working, DataConfig())
    restarted = RelayService(reopened.addresses, reopened.messages, now=lambda: now)
    assert restarted.confirm(action_id, "pushed")["status"] == "confirmed"
    assert restarted.confirm(action_id, "pushed")["status"] == "duplicate"
    assert any(item.event == "pushed" for item in reopened.messages.deliveries())


def test_data_relay_restart_redeems_issued_marker(tmp_path: Path):
    from varde_runner.relay import DataRelay

    first = DataRelay(tmp_path)
    marker = first.addresses.issue("mailman", now=datetime.now(UTC))
    restarted = DataRelay(tmp_path)

    assert asyncio.run(
        asyncio.to_thread(
            restarted.addresses.redeem,
            marker,
            "runner-restarted",
            "codex",
            ReaderContext(cwd=str(tmp_path)),
            now=datetime.now(UTC),
        )
    )
    assert any(
        item.session_id == "runner-restarted"
        for item in restarted.addresses.list_bindings()
    )

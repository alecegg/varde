from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from sqlite_addresses import SQLiteAddresses
from sqlite_messages import factory as messages_factory
from varde_data.records.addresses import ReaderContext
from varde_data.records.messages import DeliveryOutcome, NewMessage, RelayEvent

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _AddressResolver:
    def __init__(self, addresses: SQLiteAddresses) -> None:
        self.repository = addresses

    def resolve(self, name: str) -> str:
        return self.repository.resolve_alias(name)

    def addresses_for(self, slot: str) -> set[str]:
        return set(self.repository.reader_addresses(slot))

    def addresses(self, slot: str) -> set[str]:
        return self.addresses_for(slot)


def test_sqlite_schema_version_and_reopen(tmp_path: Path) -> None:
    path = tmp_path / ".cache" / "addresses.sqlite3"
    repository = SQLiteAddresses(path)
    before = cast("int", repository.version().value)

    marker = repository.issue("reader", now=NOW)
    reopened = SQLiteAddresses(path)

    assert cast("int", reopened.version().value) > before
    assert reopened.marker_error(marker, NOW) == "live binding refuses this marker"
    assert reopened.redeem(marker, "session", "harness", ReaderContext(), now=NOW)
    binding = reopened.current_binding("reader")
    assert binding is not None and binding.session_id == "session"
    assert len(reopened.events()) == 1
    with sqlite3.connect(path) as db:
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {
            "bindings",
            "tokens",
            "markers",
            "events",
            "slots",
            "aliases",
            "actions",
            "leases",
            "relay_events",
            "attempts",
            "escalations",
            "suspects",
            "retired",
            "meta",
            "mailman",
        }.issubset(tables)
        assert "state" not in tables
        assert (
            db.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0]
            == reopened.version().value
        )
        assert db.execute("SELECT COUNT(*) FROM bindings").fetchone()[0] == 1


def test_held_sqlite_write_lock_times_out(tmp_path: Path) -> None:
    path = tmp_path / "addresses.sqlite3"
    repository = SQLiteAddresses(path, busy_timeout=0.05)
    with sqlite3.connect(path, timeout=1) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        assert repository.version().value == 0
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            repository.issue("reader", now=NOW)
        assert time.monotonic() - started < 1
        blocker.rollback()


def test_alias_seed_and_confirm_delivery_across_sqlite_repositories(
    tmp_path: Path,
) -> None:
    addresses = SQLiteAddresses(tmp_path / "addresses.sqlite3")
    resolver = _AddressResolver(addresses)
    messages = messages_factory(tmp_path / "messages", resolver=resolver)
    original = messages.append(
        NewMessage("sender", "alias-a", "info", "backlog", ts="2026-01-01T00:00:00Z")
    )

    # Seed the slot reader from the beginning before publishing its new alias.
    messages.register_reader("slot-a", from_start=True)
    addresses.add_alias("slot-a", "alias-a")
    claimed = messages.claim_unread("slot-a", "session", "test", "2026-01-01T00:00:01Z")
    assert tuple(message.id for message in claimed) == (original.id,)

    confirmation_message = messages.append(
        NewMessage("sender", "alias-a", "info", "confirm me", ts="2026-01-01T00:00:02Z")
    )
    action = addresses.lease_actions(
        ({"to": "slot-a", "message_ids": [confirmation_message.id]},),
        "token",
        NOW,
    )[0]
    assert (
        addresses.begin_confirm(action.action_id, "pushed", NOW).status.value == "begun"
    )
    outcome = messages.record_relay_event(
        RelayEvent(
            str(confirmation_message.id),
            "slot-a",
            "delivered",
            "2026-01-01T00:00:03Z",
            action_created_at=action.created_at.isoformat(),
        )
    )
    assert outcome is DeliveryOutcome.RECORDED
    addresses.finish_confirm(
        action.action_id,
        "pushed",
        NOW,
        (str(confirmation_message.id),),
        ((str(confirmation_message.id), "slot-a"),),
    )

    assert addresses.action(action.action_id).status == "confirmed"  # type: ignore[union-attr]
    confirmation_deliveries = [
        (delivery.message_id, delivery.event)
        for delivery in messages.deliveries()
        if delivery.message_id == str(confirmation_message.id)
    ]
    assert confirmation_deliveries == [(str(confirmation_message.id), "delivered")]

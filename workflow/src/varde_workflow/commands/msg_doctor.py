"""Mailbox health command and pure doctor report aggregation."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.records.addresses import AddressSlot
from varde_data.views.message_receipts import (
    message_receipts,
    undelivered_deadlines,
)
from varde_data.views.msg_status import runner_relay_alive
from varde_data.views.relay_plan import classify_failure

CAUSES = ("unresolvable", "unbound", "busy", "no-receipt", "no-holder")


def aggregate_doctor(
    messages: list[dict[str, Any]],
    deliveries: list[dict[str, Any]],
    relay: dict[str, Any],
    addresses: dict[str, Any],
    now: datetime,
    *,
    role_inbox_active: bool = False,
) -> dict[str, Any]:
    """Build health, age, cause, and urgent-unread data without I/O."""
    snapshot = _canonicalize(
        messages, deliveries, addresses, role_inbox_active=role_inbox_active
    )
    normalized_messages = snapshot["messages"]
    events = snapshot["deliveries"]
    receipts = message_receipts(normalized_messages, events, now)
    overdue = _overdue_messages(normalized_messages, events, snapshot, now)
    recipients, overdue_by_cause, overdue_live, unread_urgent = _aggregate_messages(
        normalized_messages, events, receipts, overdue, snapshot
    )
    relay_status = "up" if runner_relay_alive(relay, now) else "down"
    return {
        "relay": {
            "status": relay_status,
            "current_mailman": relay.get("current_mailman"),
            "active_leases": len(relay.get("leases", [])),
        },
        "recipients": [recipients[key] for key in sorted(recipients)],
        "overdue_by_cause": {
            cause: overdue_by_cause[cause]
            for cause in CAUSES
            if overdue_by_cause[cause]
        },
        "unread_urgent": unread_urgent,
        "exit_code": int(overdue_live),
    }


def _canonicalize(
    messages, deliveries, addresses, *, role_inbox_active: bool = False
) -> dict[str, Any]:
    from varde_data.role_inbox import role_key_for_selector, role_matches_holder

    slots = addresses["slots"]
    canonical = _canonicalizer(slots)
    bindings = {canonical(address) for address in addresses["bindings"]}
    known = set(bindings)
    for slot in slots:
        known.update((slot.slot, *slot.aliases))
        if slot.current_address:
            known.add(slot.current_address)
    normalized_messages = [
        {**message, "to": canonical(str(message.get("to", "")))} for message in messages
    ]
    role_keys = {
        str(message.get("id")): role_key_for_selector(str(message.get("to", "")))
        for message in normalized_messages
        if role_inbox_active and isinstance(message.get("id"), str)
    }
    if role_inbox_active:
        live_holders = {canonical(address) for address in addresses["live_addresses"]}
        for role_key in role_keys.values():
            if role_key is None:
                continue
            known.add(role_key)
            if any(role_matches_holder(role_key, holder) for holder in live_holders):
                bindings.add(role_key)
                live_holders.add(role_key)
        normalized_deliveries = []
        for event in deliveries:
            message_id = str(event.get("message_id", ""))
            role_key = role_keys.get(message_id)
            reader = canonical(str(event.get("reader", "")))
            if role_key is not None and role_matches_holder(role_key, reader):
                reader = role_key
            normalized_deliveries.append({**event, "reader": reader})
    else:
        normalized_deliveries = [
            {**event, "reader": canonical(str(event.get("reader", "")))}
            for event in deliveries
        ]
        live_holders = {canonical(address) for address in addresses["live_addresses"]}
    return {
        "messages": normalized_messages,
        "deliveries": normalized_deliveries,
        "bindings": bindings,
        "known": known,
        "live": live_holders,
        "excluded": {canonical(address) for address in addresses["excluded_addresses"]},
    }


def _overdue_messages(messages, deliveries, snapshot, now) -> set[str]:
    unbound = {
        str(message.get("to"))
        for message in messages
        if str(message.get("to")) not in snapshot["bindings"]
    }
    deadlines = undelivered_deadlines(
        messages,
        deliveries,
        now,
        excluded_addresses=snapshot["excluded"],
        unbound_addresses=unbound,
    )
    return {message_id for message_id, deadline in deadlines.items() if deadline <= now}


def _aggregate_messages(messages, deliveries, receipts, overdue, snapshot):
    overdue_by_cause: dict[str, int] = defaultdict(int)
    recipients: dict[str, dict[str, Any]] = {}
    overdue_live = False
    urgent_ids = {
        str(event.get("message_id"))
        for event in deliveries
        if event.get("event") == "urgent"
    }
    unread_urgent: list[str] = []

    for message in messages:
        message_id = message.get("id")
        address = message.get("to")
        if not isinstance(message_id, str) or not isinstance(address, str):
            continue
        if (
            address != "main"
            and address in snapshot["excluded"]
            and address not in snapshot["live"]
        ):
            continue
        recipient_state = (
            receipts.get(message_id, {}).get("recipients", {}).get(address, {})
        )
        state = recipient_state.get("state")
        age = recipient_state.get("undelivered_age_seconds")
        if message_id in urgent_ids and state not in {"read", "answered"}:
            unread_urgent.append(message_id)
        if state not in {"queued", "pushed"} or not isinstance(age, (int, float)):
            continue
        row = recipients.setdefault(
            address,
            {"address": address, "undelivered": 0, "oldest_age_seconds": None},
        )
        row["undelivered"] += 1
        oldest = row["oldest_age_seconds"]
        row["oldest_age_seconds"] = age if oldest is None else max(oldest, age)
        if message_id not in overdue:
            continue
        cause_text = classify_failure(
            deliveries, message_id, address, snapshot["bindings"], snapshot["known"]
        )
        cause = cause_text.partition(" ")[0]
        overdue_by_cause[cause] += 1
        overdue_live |= address in snapshot["live"]
    return recipients, overdue_by_cause, overdue_live, sorted(unread_urgent)


def _canonicalizer(slots: tuple[AddressSlot, ...] | list[AddressSlot]):
    lookup: dict[str, str] = {}
    for slot in slots:
        lookup[slot.slot] = slot.slot
        for alias in slot.aliases:
            lookup[alias] = slot.slot
        if slot.current_address:
            lookup[slot.current_address] = slot.slot

    def canonical(address: str) -> str:
        return lookup.get(address, address)

    return canonical


def run(args, working: str | Path) -> int:
    """Load mailbox and relay state, then print the doctor report."""
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    from varde_workflow.inbox import delivery_events, read_all
    from varde_workflow.relay_state import load

    now = datetime.now(UTC)
    data = open_data(Path(working), load_data_config())
    from varde_data.role_inbox import select_role_inbox

    role_inbox_active = select_role_inbox(Path(working)) is not None
    messages = [message.to_dict() for message in read_all(working)]
    excluded = set(data.addresses.retired_records())
    report = aggregate_doctor(
        messages,
        delivery_events(working),
        load(working),
        {
            "slots": data.addresses.slots(),
            "bindings": {binding.address for binding in data.addresses.list_bindings()},
            "live_addresses": data.addresses.live_addresses(now),
            "excluded_addresses": excluded,
        },
        now,
        role_inbox_active=role_inbox_active,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"runner relay: {report['relay']['status']}")
        for row in report["recipients"]:
            print(
                f"{row['address']}: {row['undelivered']} undelivered, "
                f"{_age(row['oldest_age_seconds'])} oldest"
            )
        causes = (
            ", ".join(
                f"{cause}={count}"
                for cause, count in report["overdue_by_cause"].items()
            )
            or "none"
        )
        print("overdue by cause: " + causes)
        print(f"unread urgent: {len(report['unread_urgent'])}")
    return report["exit_code"]


def _age(seconds: float | None) -> str:
    return "none" if seconds is None else f"{int(seconds)}s"

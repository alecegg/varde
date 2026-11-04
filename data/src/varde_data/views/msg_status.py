"""Backend-neutral status calculations for message records."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from varde_data.repos.messages import MessageRepository
from varde_data.views.message_receipts import message_receipts
from varde_data.views.relay_liveness import (
    RUNNER_WAITING_STALE_SECONDS,
    elapsed,
    mailman_alive,
)

LEGACY_STORE_DIR = "memory-bank"
ALERT_EVENTS = {"suspect", "misdelivered", "token-reuse", "supersede"}


def find_stray_stores(root: Path | None, working: Path) -> list[Path]:
    """Find inbox directories under a repo, excluding the configured store."""
    if root is None:
        return []
    expected = working / ".cache" / "inbox"
    excluded = {".git", "node_modules", ".venv", "__pycache__"}
    found = []
    for directory, names, _files in os.walk(root):
        current = Path(directory)
        names[:] = [name for name in names if name not in excluded]
        if current == root / ".varde" and "worktrees" in names:
            names.remove("worktrees")
        if (
            current.name == "inbox"
            and current.parent.name == ".cache"
            and current.parent.parent.name == "working"
            and current.parent.parent.parent.name == LEGACY_STORE_DIR
        ):
            if current != expected:
                found.append(current)
            names.clear()
    return sorted(found)


def status_messages(
    repository: MessageRepository, below_watermark_ids: Iterable[str] = ()
) -> list[dict[str, Any]]:
    """Convert repository messages to the status view's JSON-compatible rows."""
    suppressed = set(below_watermark_ids)
    messages = []
    for message in repository.read_all().records:
        entry: dict[str, Any] = {
            "ts": message.ts,
            "from": message.from_,
            "to": message.to,
            "kind": message.kind,
            "text": message.text,
            **({"notes": message.notes} if message.notes is not None else {}),
            **({"id": message.id} if message.id is not None else {}),
            **({"reply_to": message.reply_to} if message.reply_to is not None else {}),
        }
        if message.legacy_id is not None:
            entry["_legacy_idless"] = True
        if message.id in suppressed:
            entry["_below_watermark"] = True
        messages.append(entry)
    return messages


def runner_relay_alive(state: dict[str, Any], now: datetime) -> bool:
    """Read runner liveness from its current relay identity and latest event.

    A current waiting event stays active until its next heartbeat is overdue.
    """
    token_id = state.get("current_mailman")
    events = state.get("events")
    if not isinstance(token_id, str) or not token_id or not isinstance(events, list):
        return False
    latest = next(
        (
            event
            for event in reversed(events)
            if isinstance(event, dict) and event.get("token_id") == token_id
        ),
        None,
    )
    if not isinstance(latest, dict):
        return False
    if latest.get("event") == "waiting":
        try:
            at = datetime.fromisoformat(str(latest["at"]))
        except KeyError, ValueError:
            return False
        age = elapsed(at, now, events)
        return age < timedelta(seconds=RUNNER_WAITING_STALE_SECONDS)
    return latest.get("event") == "returned" and mailman_alive(token_id, now, events)


def parse_time(value: str) -> datetime:
    """Parse an ISO timestamp and normalize it to UTC."""
    parsed = datetime.fromisoformat(value)
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


def percentile(values: list[float], percentile: int) -> float | None:
    """Return the nearest-rank percentile, or None for no observations."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, (len(ordered) * percentile + 99) // 100 - 1)]


def _urgent_due(
    messages: list[dict[str, Any]],
    state: dict,
    bindings,
    current: datetime,
    is_urgent: Callable,
) -> bool:
    return any(
        is_urgent(message, bindings)
        and message.get("id")
        and not message.get("_legacy_idless")
        and _is_pending(message, state)
        and current - parse_time(str(message["ts"])) >= timedelta(minutes=3)
        for message in messages
    )


def _is_pending(message: dict[str, Any], state: dict) -> bool:
    history = state.get((str(message.get("to", "")), str(message.get("id", ""))), {})
    return not (
        history.get("delivered")
        or history.get("dropped")
        or history.get("legacy")
        or message.get("_below_watermark")
    )


def _stopped_readers(messages, bindings, state, current, leases, index):
    stopped = []
    for binding in bindings:
        address = str(binding.get("address", ""))
        pending = [
            item
            for item in messages
            if item.get("to") == address and _is_pending(item, state)
        ]
        last_seen = binding.get("last_seen")
        if (
            not pending
            or not last_seen
            or current - parse_time(str(last_seen)) <= timedelta(minutes=30)
        ):
            continue
        oldest = min(parse_time(str(item["ts"])) for item in pending)
        if current - oldest <= timedelta(minutes=10):
            continue
        pushed_recently = any(
            item.get("event") == "pushed"
            and current - parse_time(str(item["at"])) <= timedelta(minutes=30)
            for item in index["by_reader"].get(address, [])
        )
        leased_recently = any(
            lease.get("address", lease.get("to")) == address
            and current - parse_time(str(lease.get("created_at", "")))
            <= timedelta(minutes=30)
            for lease in leases
        )
        if pushed_recently or leased_recently:
            continue
        newer = [
            item
            for item in bindings
            if item.get("address") == address
            and item.get("bound_at", "") > binding.get("bound_at", "")
        ]
        stopped.append(
            {
                "address": address,
                "newer_binding": str(newer[-1].get("session_id")) if newer else None,
            }
        )
    return stopped


def _event_index(events: list[dict[str, Any]]) -> dict[str, Any]:
    by_message: dict[str, list[dict[str, Any]]] = {}
    by_reader: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        if isinstance(event.get("message_id"), str):
            by_message.setdefault(event["message_id"], []).append(event)
        if isinstance(event.get("reader"), str):
            by_reader.setdefault(event["reader"], []).append(event)
    return {"by_message": by_message, "by_reader": by_reader}


def _message_details(messages, deliveries, events, state, index):
    details = []
    for message in messages:
        mid = str(message.get("id", ""))
        history = state.get((str(message.get("to", "")), mid), {})
        related: dict[str, list[dict[str, Any]]] = {}
        for item in index["by_message"].get(mid, []):
            related.setdefault(str(item.get("event", "")), []).append(item)
        pushed = next(iter(related.get("pushed", [])), None)
        details.append(
            {
                "id": mid,
                "sent": message.get("ts"),
                "pushed": pushed.get("at") if pushed else None,
                "delivered": history.get("delivered", {}).get("at"),
                "acked": history.get("acked", {}).get("at"),
                "suspect": len(related.get("suspect", [])),
                "misdelivered": len(related.get("misdelivered", [])),
            }
        )
    return details


def _recent_alerts(
    events: list[dict[str, Any]], current: datetime
) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("event") in ALERT_EVENTS
        and not (event.get("event") == "supersede" and event.get("prior_live") is False)
        and timedelta(0)
        <= current - parse_time(str(event["at"]))
        <= timedelta(hours=24)
    ]


def _address_rows(messages, state, receipts, bindings, current, is_urgent):
    binding_map = {str(item.get("address")): item for item in bindings}
    addresses: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        addresses.setdefault(str(message.get("to", "")), []).append(message)
    bound = {str(item.get("address")) for item in bindings}
    rows, unbound_pending = [], []
    overdue = False
    for address, items in sorted(addresses.items()):
        pending, unacked, last_delivery = [], 0, None
        for message in items:
            history = state.get((address, str(message.get("id", ""))), {})
            delivered, acked = history.get("delivered"), history.get("acked")
            if delivered and (
                last_delivery is None or str(delivered["at"]) > last_delivery["at"]
            ):
                last_delivery = delivered
            if delivered and not acked:
                unacked += 1
            if _is_pending(message, state):
                pending.append(message)
        unread_times = [parse_time(str(item["ts"])) for item in pending]
        oldest_age = max(
            (
                max(0.0, (current - parse_time(str(item["ts"]))).total_seconds())
                for item in pending
            ),
            default=None,
        )
        undelivered = [
            message
            for message in items
            if receipts.get(str(message.get("id", "")), {})
            .get("recipients", {})
            .get(address, {})
            .get("state")
            in {"queued", "pushed"}
        ]
        oldest_undelivered_age = max(
            (
                max(0.0, (current - parse_time(str(item["ts"]))).total_seconds())
                for item in undelivered
            ),
            default=None,
        )
        row_overdue = False
        urgent_due = False
        for message in pending:
            limit = 600 if is_urgent(message, binding_map) else 1800
            age = (current - parse_time(str(message["ts"]))).total_seconds()
            row_overdue |= age > limit
            urgent_due |= (
                is_urgent(message, binding_map)
                and message.get("id")
                and not message.get("_legacy_idless")
                and age >= 180
            )
        overdue |= row_overdue
        if pending and address not in bound:
            unbound_pending.append(address)
        rows.append(
            {
                "address": address,
                "total": len(items),
                "unread": len(pending),
                "oldest_unread_age_seconds": oldest_age,
                "oldest_undelivered_age_seconds": oldest_undelivered_age,
                "newest_unread_at": (
                    max(unread_times).isoformat() if unread_times else None
                ),
                "overdue": row_overdue,
                "urgent_due": urgent_due,
                "delivered_not_acked": unacked,
                "last_delivery": last_delivery,
                "last_delivery_channel": last_delivery.get("via")
                if last_delivery
                else None,
            }
        )
    return rows, unbound_pending, overdue


def _default_urgent(message: dict[str, Any], _bindings: object) -> bool:
    return message.get("kind") in {"needs-user", "blocked", "merge-ready", "stale"}


def build_report(  # noqa: PLR0913, PLR0917
    messages: list[dict[str, Any]],
    deliveries: list[dict[str, Any]],
    events: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    now: datetime,
    relay: dict[str, Any] | None = None,
    is_urgent: Callable | None = None,
) -> dict[str, Any]:
    """Build an immutable-style status snapshot from inbox records."""
    current = now.astimezone(UTC)
    if is_urgent is None:
        is_urgent = _default_urgent
    index = _event_index(deliveries + events)
    message_by_id = {str(item["id"]): item for item in messages if item.get("id")}
    state: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    delivered_latency: list[float] = []
    ack_latency: list[float] = []
    cli_main: dict[str, dict[str, Any]] = {}
    for entry in deliveries:
        key = (str(entry.get("reader", "")), str(entry.get("message_id", "")))
        state.setdefault(key, {}).setdefault(str(entry.get("event", "")), entry)
        if (
            key[0] == "main"
            and entry.get("via") == "cli"
            and entry.get("event") in {"delivered", "acked"}
        ):
            prior = cli_main.get(key[1])
            if prior is None or str(entry.get("at", "")) > str(prior.get("at", "")):
                cli_main[key[1]] = entry

    for (_, message_id), history in state.items():
        message = message_by_id.get(message_id)
        if not message:
            continue
        sent = parse_time(str(message["ts"]))
        delivered = history.get("delivered")
        acked = history.get("acked")
        if delivered:
            delivered_latency.append(
                max(0.0, (parse_time(str(delivered["at"])) - sent).total_seconds())
            )
        if acked:
            ack_latency.append(
                max(0.0, (parse_time(str(acked["at"])) - sent).total_seconds())
            )

    receipts = message_receipts(messages, deliveries, current)
    rows, unbound_pending, overdue = _address_rows(
        messages, state, receipts, bindings, current, is_urgent
    )

    recent_events = _recent_alerts(
        events
        + [
            item
            for item in deliveries
            if item.get("event") in {"suspect", "misdelivered"}
        ],
        current,
    )
    relay = relay or {"mailman": "none", "mailmen": []}
    binding_map = {str(item.get("address")): item for item in bindings}
    urgent_due = _urgent_due(messages, state, binding_map, current, is_urgent)
    runner_relay_down_with_urgent_mail = (
        relay.get("runner_relay") != "up" and urgent_due
    )
    stopped_reading = _stopped_readers(
        messages, bindings, state, current, (relay or {}).get("leases", []), index
    )
    bad = (
        overdue
        or runner_relay_down_with_urgent_mail
        or bool(recent_events)
        or bool(unbound_pending)
    )
    message_details = _message_details(messages, deliveries, events, state, index)
    return {
        "addresses": rows,
        "send_to_delivered_seconds": {
            "p50": percentile(delivered_latency, 50),
            "p90": percentile(delivered_latency, 90),
        },
        "send_to_ack_seconds": {
            "p50": percentile(ack_latency, 50),
            "p90": percentile(ack_latency, 90),
        },
        "unbound_pending": unbound_pending,
        "events": recent_events,
        "messages": message_details,
        "cli_main_reads": {
            "count": len(cli_main),
            "last_at": max(
                (str(item.get("at", "")) for item in cli_main.values()), default=None
            ),
        },
        "overdue": overdue,
        "runner_relay": relay.get("runner_relay", "down"),
        "runner_relay_down_with_urgent_mail": runner_relay_down_with_urgent_mail,
        "stopped_reading": stopped_reading,
        "bad": bad,
        "exit_code": 1 if bad else 0,
    }


def filter_retired(report: dict[str, Any], retired: dict[str, str]) -> dict[str, Any]:
    """Hide retired addresses unless they received unread mail after retirement."""
    retired_addresses = {
        address for address in retired if not address.startswith("mailman:")
    }
    addresses = []
    for row in report["addresses"]:
        address = row["address"]
        stamp = retired.get(address)
        newest = row.get("newest_unread_at")
        if address not in retired_addresses or (
            row["unread"] > 0
            and stamp is not None
            and newest is not None
            and parse_time(str(newest)) > parse_time(stamp)
        ):
            addresses.append(row)
    visible = {row["address"] for row in addresses}
    filtered = {
        **report,
        "addresses": [
            {
                key: value
                for key, value in row.items()
                if key not in {"newest_unread_at", "overdue", "urgent_due"}
            }
            for row in addresses
        ],
        "overdue": any(row.get("overdue", False) for row in addresses),
        "runner_relay_down_with_urgent_mail": report.get("runner_relay", "down") != "up"
        and any(row.get("urgent_due", False) for row in addresses),
        "unbound_pending": [
            address for address in report["unbound_pending"] if address in visible
        ],
        "stopped_reading": [
            item for item in report["stopped_reading"] if item["address"] in visible
        ],
        "events": [
            event
            for event in report["events"]
            if (
                event_address := event.get(
                    "address", event.get("reader", event.get("to"))
                )
            )
            not in retired_addresses
            or event_address in visible
        ],
    }
    filtered["bad"] = bool(
        filtered["overdue"]
        or filtered["runner_relay_down_with_urgent_mail"]
        or filtered["events"]
        or filtered["unbound_pending"]
    )
    filtered["exit_code"] = 1 if filtered["bad"] else 0
    return filtered


def banner(report: dict[str, Any]) -> str | None:
    """Return a single-line alert when the report needs attention."""
    if not report.get("bad"):
        return None
    details = []
    if report.get("unbound_pending"):
        details.append("pending mail for unbound addresses")
    if report.get("events"):
        details.append("recent address security events")
    if report.get("overdue"):
        details.append("undelivered mail is overdue")
    if report.get("runner_relay_down_with_urgent_mail"):
        details.append(
            f"runner relay: {report.get('runner_relay', 'down')}; urgent mail is due"
        )
        if report.get("mailman", "none") == "none":
            details.append("mailman: none")
    return "varde msg status: " + "; ".join(details)

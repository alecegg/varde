"""Pure evaluation of mail reliability soak records."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from varde_core.utc import in_window, window_start

from varde_workflow.merge_state import APPROVED_MERGE_GRACE_SECONDS
from varde_workflow.msg_status import parse_time, percentile

DEFAULT_THRESHOLDS = {
    "delivered-latency": 120,
    "ack-latency": 30 * 60,
    "main-nudges": 0,
    "replays": 0,
    "status-clean": 0,
    "send-no-mailman": 0.02,
    "merge-guard": 0,
    "parity": 0,
    "minimum-parity-compares": 1,
    "minimum_messages": 5,
}


def _time(value: Any) -> datetime | None:
    # Unlike the shared parser, parse_time uses astimezone(UTC) and raises ValueError.
    if not isinstance(value, str):
        return None
    try:
        return parse_time(value)
    except ValueError:
        return None


def _in_window(value: Any, start: datetime, end: datetime) -> bool:
    timestamp = _time(value)
    return timestamp is not None and in_window(timestamp, start, end)


def _window_messages(messages: list[dict[str, Any]], start: datetime, now: datetime):
    return {
        str(message["id"]): message
        for message in messages
        if message.get("id") and _in_window(message.get("ts"), start, now)
    }


def _ordered_events(events: list[dict[str, Any]]):
    """Keep valid timestamps and sort by time, preserving input log order on ties."""
    ordered = []
    for index, event in enumerate(events):
        timestamp = _time(event.get("at"))
        if timestamp is not None:
            ordered.append((timestamp, index, event))
    return sorted(ordered, key=lambda item: (item[0], item[1]))


def _latency_values(messages, deliveries, event_name):
    by_message_reader: dict[
        tuple[str, str], list[tuple[datetime, int, dict[str, Any]]]
    ] = {}
    for timestamp, index, event in _ordered_events(deliveries):
        if event.get("event") != event_name:
            continue
        key = (str(event.get("message_id", "")), str(event.get("reader", "")))
        by_message_reader.setdefault(key, []).append((timestamp, index, event))

    results = []
    for message_id, message in messages.items():
        reader = message.get("to")
        if not reader or reader == "main":
            continue
        sent = _time(message.get("ts"))
        events = by_message_reader.get((message_id, str(reader)), [])
        if sent is not None and events:
            results.append(max(0.0, (events[0][0] - sent).total_seconds()))
    return results


def _wake_metrics(messages, deliveries, live_addresses, now, threshold):
    delivered_keys = set()
    delivered_at = {}
    for timestamp, _, event in _ordered_events(deliveries):
        if event.get("event") != "delivered":
            continue
        key = (str(event.get("message_id", "")), str(event.get("reader", "")))
        delivered_keys.add(key)
        delivered_at.setdefault(key, timestamp)

    wakes = 0
    missed = 0
    recipients = set()
    latencies = []
    for message_id, message in messages.items():
        recipient = message.get("to")
        if not recipient or recipient == "main" or recipient not in live_addresses:
            continue
        sent_at = _time(message.get("ts"))
        key = (message_id, str(recipient))
        if key in delivered_keys:
            wakes += 1
            recipients.add(str(recipient))
            delivered_time = delivered_at.get(key)
            if sent_at is not None and delivered_time is not None:
                latencies.append(max(0.0, (delivered_time - sent_at).total_seconds()))
            continue
        if sent_at is not None and (now - sent_at).total_seconds() > threshold:
            missed += 1
    return {
        "wakes": wakes,
        "missed": missed,
        "distinct_recipients": len(recipients),
        "max_delivered_latency_s": max(latencies, default=None),
    }


def _latency_criterion(
    identifier, event_name, messages, deliveries, threshold, minimum
):
    values = _latency_values(messages, deliveries, event_name)
    insufficient = len(values) < minimum
    value = percentile(values, 95)
    return _criterion(
        identifier,
        value,
        threshold,
        len(values),
        ok=insufficient or value <= threshold,
        insufficient=insufficient,
    )


def _main_nudges(nudges, now, threshold):
    start = window_start(now, hours=24)
    count = 0
    for item in nudges:
        timestamp = _time(item.get("at"))
        if (
            item.get("event") == "main-nudge"
            and timestamp is not None
            and in_window(timestamp, start, now)
        ):
            count += 1
    return _criterion("main-nudges", count, threshold, count)


def _replay_count(history, sleeps, sent_at):
    ack_order = None
    count = 0
    for timestamp, index, event in history:
        if event.get("event") == "acked":
            ack_order = (timestamp, index)
            continue
        if event.get("event") != "delivered" or ack_order is None:
            continue
        delivered_order = (timestamp, index)
        if any(
            ack_order < (slept_at, slept_index) < delivered_order
            and sent_at <= slept_at
            for slept_at, slept_index in sleeps
        ):
            count += 1
    return count


def _replays(messages, relay_events, threshold):
    """Detect relay-wide sleeps; relay_state prunes them after one day."""
    by_message_reader: dict[
        tuple[str, str], list[tuple[datetime, int, dict[str, Any]]]
    ] = {}
    sleeps = []
    for timestamp, index, event in _ordered_events(relay_events):
        if event.get("event") == "slept":
            sleeps.append((timestamp, index))
            continue
        key = (str(event.get("message_id", "")), str(event.get("reader", "")))
        by_message_reader.setdefault(key, []).append((timestamp, index, event))
    count = 0
    for message_id, message in messages.items():
        reader = str(message.get("to", ""))
        sent_at = _time(message.get("ts"))
        history = by_message_reader.get((message_id, reader), [])
        if sent_at is not None:
            count += _replay_count(history, sleeps, sent_at)
    return _criterion("replays", count, threshold, len(messages))


def _status_clean(status, threshold):
    bad = status.get("exit_code") != 0
    return _criterion("status-clean", int(bad), threshold, 1)


def _send_no_mailman(events, start, end, threshold, minimum):
    sends = [
        event
        for event in events
        if event.get("event") == "send-liveness"
        and _in_window(event.get("at"), start, end)
    ]
    failed = sum(event.get("alive") is False for event in sends)
    insufficient = len(sends) < minimum
    value = failed / len(sends) if sends else None
    return _criterion(
        "send-no-mailman",
        value,
        threshold,
        len(sends),
        ok=insufficient or value <= threshold,
        insufficient=insufficient,
    )


def _merge_guard(data, current, threshold):
    approved = data.get("approved_merges", [])
    bad = bool(data.get("open_requests", []))
    for item in approved:
        if item.get("merged"):
            continue
        approved_at = _time(item.get("approved_at"))
        if (
            approved_at is None
            or (current - approved_at).total_seconds() >= APPROVED_MERGE_GRACE_SECONDS
        ):
            bad = True
    count = len(approved) + len(data.get("open_requests", []))
    return _criterion("merge-guard", int(bad), threshold, count)


def _parity_criterion(report, threshold, minimum):
    """Evaluate mirror comparisons; absence means this is not a mirror backend."""
    if report is None:
        return None
    compares = int(report.get("compared", 0))
    failures = sum(
        int(report.get(kind, 0)) for kind in ("divergence", "mirror-failure", "lag")
    )
    insufficient = compares < minimum
    return _criterion(
        "parity",
        "no-data" if insufficient else failures,
        threshold,
        compares + failures,
        ok=not insufficient and failures <= threshold,
        insufficient=insufficient,
    )


def _criterion(identifier, value, threshold, count, *, ok=None, insufficient=False):
    if ok is None:
        ok = value is None or value <= threshold
    return {
        "id": identifier,
        "value": value,
        "threshold": threshold,
        "ok": bool(ok),
        "n": count,
        "insufficient": insufficient,
    }


def _streak(prior_days, current_date: date, today_ok):
    by_date = {}
    for item in prior_days:
        try:
            item_date = date.fromisoformat(item.get("date", ""))
        except TypeError, ValueError:
            continue
        if item_date < current_date:
            by_date[item_date] = bool(item.get("all_ok"))
    if not today_ok:
        return 0
    streak = 1
    day = current_date - timedelta(days=1)
    while by_date.get(day) is True:
        streak += 1
        day -= timedelta(days=1)
    return streak


def evaluate(
    data: dict[str, Any], window_days: int, now: datetime, thresholds: dict[str, Any]
) -> dict[str, Any]:
    """Evaluate plain records; the gatherer must keep append-log order per list."""
    limits = {**DEFAULT_THRESHOLDS, **thresholds}
    current = now.astimezone(UTC)
    start = window_start(current, days=window_days)
    messages = _window_messages(data.get("messages", []), start, current)
    live_addresses = set(data.get("live_addresses", []))
    live_messages = {
        key: message
        for key, message in messages.items()
        if message.get("to") in live_addresses
    }
    deliveries = [
        event
        for event in data.get("deliveries", [])
        if event.get("message_id") in messages
    ]
    minimum = int(limits["minimum_messages"])
    wake_metrics = _wake_metrics(
        live_messages,
        deliveries,
        live_addresses,
        current,
        float(limits["delivered-latency"]),
    )
    criteria = [
        _latency_criterion(
            "delivered-latency",
            "delivered",
            live_messages,
            deliveries,
            limits["delivered-latency"],
            minimum,
        ),
        _latency_criterion(
            "ack-latency",
            "acked",
            live_messages,
            deliveries,
            limits["ack-latency"],
            minimum,
        ),
        _main_nudges(data.get("nudges", []), current, limits["main-nudges"]),
        _replays(messages, data.get("relay_events", []), limits["replays"]),
        _status_clean(data.get("status", {}), limits["status-clean"]),
        _send_no_mailman(
            data.get("relay_events", []),
            start,
            current,
            limits["send-no-mailman"],
            minimum,
        ),
        _merge_guard(data, current, limits["merge-guard"]),
    ]
    parity = _parity_criterion(
        data.get("parity"), limits["parity"], int(limits["minimum-parity-compares"])
    )
    if parity is not None:
        criteria.append(parity)
    active = int(data.get("active_orchestrators_today", 0))
    all_ok = all(item["ok"] for item in criteria) and active >= 1
    return {
        "date": current.date().isoformat(),
        "window_days": window_days,
        "undeliverable": sum(
            message.get("to") not in live_addresses for message in messages.values()
        ),
        "criteria": criteria,
        "active_orchestrators": active,
        "all_ok": all_ok,
        "days_ok_streak": _streak(data.get("prior_days", []), current.date(), all_ok),
        **wake_metrics,
    }

"""Pure planning predicates and action selection for the message relay."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from varde_data.roles import role_for_address
from varde_data.views.message_receipts import undelivered_deadlines

URGENT = {
    "needs-user",
    "decision-needed",
    "blocked",
    "merge-ready",
    "stale",
}
IMMEDIATE = {"needs-user", "decision-needed", "blocked", "merge-ready"}
RECEIPT_CAPABLE = {"claude", "codex"}


def classify_failure(
    events: list[dict[str, Any]],
    message_id: str,
    recipient: str,
    bindings: set[str],
    known_addresses: set[str],
    failures: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> str:
    """Classify why an undelivered message needs escalation."""
    failure = (
        failures.get((message_id, recipient))
        if failures is not None
        else next(
            (
                event
                for event in reversed(events)
                if event.get("message_id") == message_id
                and event.get("reader") == recipient
                and event.get("event") in {"failed", "skipped-busy", "target-gone"}
            ),
            None,
        )
    )
    if failure and failure.get("event") == "skipped-busy":
        return _with_reason("busy", failure.get("reason"))
    if failure and (
        failure.get("event") == "target-gone" or failure.get("reason") == "unresolvable"
    ):
        return _with_reason("unresolvable", failure.get("reason"))
    if recipient in bindings:
        return _with_reason("no-receipt", failure.get("reason") if failure else None)
    if recipient not in known_addresses:
        return _with_reason("unresolvable", failure.get("reason") if failure else None)
    return "no-holder" if role_for_address(recipient) else "unbound"


def _with_reason(cause: str, reason: Any) -> str:
    return f"{cause} ({reason})" if isinstance(reason, str) and reason else cause


def _time(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return fallback
    return fallback


def _events(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in state.get("events", []) if isinstance(item, dict)]


def _mark_urgent_messages(
    state: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    urgent_ids = {
        str(event.get("message_id"))
        for event in events
        if event.get("event") == "urgent"
    }
    return {
        **state,
        "messages": [
            {**message, "urgent": True}
            if isinstance(message, dict) and str(message.get("id")) in urgent_ids
            else message
            for message in state.get("messages", [])
        ],
    }


def event_index(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Index one event snapshot for planner predicates."""
    by_message: dict[str, list[dict[str, Any]]] = {}
    by_reader: dict[str, list[dict[str, Any]]] = {}
    by_message_reader: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_source: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        message_id = event.get("message_id")
        reader = event.get("reader")
        if isinstance(message_id, str):
            by_message.setdefault(message_id, []).append(event)
        if isinstance(reader, str):
            by_reader.setdefault(reader, []).append(event)
        if isinstance(reader, str) and isinstance(message_id, str):
            by_message_reader.setdefault((message_id, reader), []).append(event)
        source = event.get("source_id")
        if isinstance(source, str):
            by_source.setdefault(source, []).append(event)
    return {
        "by_message": by_message,
        "by_reader": by_reader,
        "by_message_reader": by_message_reader,
        "by_source": by_source,
        "slept": [item for item in events if item.get("event") == "slept"],
        "all": events,
    }


def _message_events(
    events: list[dict[str, Any]], index: dict[str, Any] | None, message_id: str
) -> list[dict[str, Any]]:
    return (
        index["by_message"].get(message_id, [])
        if index
        else [event for event in events if event.get("message_id") == message_id]
    )


def is_urgent(message: dict[str, Any], bindings: dict[str, dict[str, Any]]) -> bool:
    kind = message.get("kind", "info")
    if kind in URGENT:
        return True
    recipient = message.get("to")
    return (
        kind == "done" and recipient in bindings and message.get("from") not in bindings
    )


def _relay_urgent(message: dict[str, Any], bindings: dict[str, dict[str, Any]]) -> bool:
    """Urgency for relay timing, including only coordinator hand-backs."""
    if message.get("kind") == "done":
        recipient = message.get("to")
        return recipient in bindings and (
            recipient == "main" or recipient.startswith("orchestrator-")
        )
    return is_urgent(message, bindings)


def receipt_pending(
    events: list[dict[str, Any]],
    message_id: str,
    index: dict[str, Any] | None = None,
    *,
    reader: str | None = None,
) -> dict[str, Any] | None:
    related = [
        event
        for event in _message_events(events, index, message_id)
        if reader is None or event.get("reader") == reader
    ]
    for event in reversed(related):
        if event.get("event") != "pushed":
            continue
        if event.get("harness") not in RECEIPT_CAPABLE:
            return None
        if any(
            item.get("event") == "suspect"
            and item.get("action_id") == event.get("action_id")
            for item in related
        ):
            return None
        return event
    return None


def backoff_until(
    events: list[dict[str, Any]],
    message_id: str,
    attempts: list[dict[str, Any]] | None = None,
    index: dict[str, Any] | None = None,
    *,
    reader: str | None = None,
) -> datetime | None:
    rows = [
        event
        for event in _message_events(events, index, message_id)
        if event.get("event") in {"skipped-busy", "failed", "suspect"}
        and (reader is None or event.get("reader") == reader)
    ]
    if attempts and reader is None:
        rows = [
            {"event": item.get("result"), "at": item.get("at")} for item in attempts
        ]
    if not rows:
        return None
    latest = rows[-1]
    result = latest.get("event", latest.get("result"))
    group = [row for row in rows if row.get("event", row.get("result")) == result]
    delays = (1, 2, 5) if result == "skipped-busy" else (1, 5, 15)
    delay = delays[min(len(group) - 1, len(delays) - 1)]
    return _time(latest.get("at"), datetime.min) + timedelta(minutes=delay)


def _backoff(
    events: list[dict[str, Any]], message_id: str
) -> tuple[int, datetime | None]:
    """Compatibility alias for the original internal helper."""
    attempts = [
        event
        for event in events
        if event.get("message_id") == message_id
        and event.get("event") in {"skipped-busy", "failed", "suspect"}
    ]
    return len(attempts), backoff_until(events, message_id)


def _delivered(
    events: list[dict[str, Any]], mid: str, address: str, index=None
) -> bool:
    related = (
        index["by_message_reader"].get((mid, address), [])
        if index
        else _message_events(events, None, mid)
    )
    return any(
        event.get("event") in {"delivered", "dropped", "legacy", "target-gone"}
        for event in related
    )


def _shifted(
    start: datetime,
    duration: timedelta,
    events: list[dict[str, Any]],
    now: datetime | None = None,
    index: dict[str, Any] | None = None,
) -> datetime:
    gap = sum(
        max(0.0, float(event.get("gap_seconds", 0)))
        for event in (index["slept"] if index else events)
        if event.get("event") == "slept"
        if start < _time(event.get("at"), start)
        and (now is None or _time(event.get("at"), start) <= now)
        if isinstance(event.get("gap_seconds", 0), (int, float))
    )
    return start + duration + timedelta(seconds=gap)


def _message_due(  # noqa: PLR0911, PLR0913, PLR0917
    message: dict[str, Any],
    now: datetime,
    bindings: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
    config: dict[str, Any],
    attempts: list[dict[str, Any]] | None = None,
    index: dict[str, Any] | None = None,
) -> tuple[str | None, datetime | None, bool]:
    mid, address = message.get("id"), message.get("to")
    if not isinstance(mid, str) or not isinstance(address, str):
        return "unbound", None, False
    binding = bindings.get(address)
    if binding is None or binding.get("wake") == "gone":
        return "unbound", None, False
    if _delivered(events, mid, address, index):
        return None, None, False
    if address == "main" and message.get("from") == "relay":
        return None, None, False
    urgent = bool(message.get("urgent")) or _relay_urgent(message, bindings)
    sent = _time(message.get("ts"), now)
    if not urgent:
        digest_due = _shifted(
            sent,
            timedelta(minutes=int(config.get("digest_minutes", 2))),
            events,
            now,
            index,
        )
        if now < digest_due:
            return "active", digest_due, urgent
    last_seen = _time(binding.get("last_seen"), datetime.min.replace(tzinfo=now.tzinfo))
    grace_due = _shifted(sent, timedelta(seconds=120), events, now, index)
    immediate = (
        bool(message.get("urgent"))
        or message.get("kind") in IMMEDIATE
        or (message.get("kind") == "done" and urgent)
    )
    if not immediate and now < grace_due and now - last_seen <= timedelta(seconds=120):
        return "active", grace_due, urgent
    shared_role = bool(message.get("_shared_role_mail"))
    pushed = receipt_pending(
        events, mid, index, reader=str(address) if shared_role else None
    )
    if pushed:
        due = _shifted(
            _time(pushed.get("at"), now),
            timedelta(minutes=int(config.get("receipt_minutes", 10))),
            events,
            now,
            index,
        )
        if now < due:
            return "backoff", due, urgent
    retries = [
        e
        for e in _message_events(events, index, mid)
        if e.get("event") in {"failed", "suspect"}
    ]
    retry = backoff_until(
        events,
        mid,
        None if shared_role else attempts,
        index,
        reader=str(address) if shared_role else None,
    )
    if retry and now < retry:
        return "backoff", retry, urgent
    if len(retries) >= 3 and address != "main":
        return None, None, urgent
    return None, now, urgent


def plan(
    state: dict[str, Any],
    now: datetime,
    config: dict[str, Any] | None = None,
    *,
    resolve_reader: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    state = resolve_slot_addresses(state, resolve_reader)
    events = _events(state)
    state = _mark_urgent_messages(state, events)
    return _plan(state, now, config or {}, events, event_index(events))


def _plan(
    state: dict[str, Any],
    now: datetime,
    config: dict[str, Any],
    events: list[dict[str, Any]],
    index: dict[str, Any],
) -> dict[str, Any]:
    """Build E2 response shape, grouping due messages by bound recipient."""
    bindings = _bindings(state)
    grouped, deferred = _group_due_messages(state, now, config, events, index, bindings)
    actions = _build_actions(grouped, deferred, bindings, now, config)
    escalations = _escalations(state, events, now)
    actions.sort(key=lambda item: (item["tier"] != "urgent", item["to"]))
    return {
        "actions": actions,
        "deferred": list(deferred.values()),
        "escalations": escalations,
    }


def _bindings(state):
    return {
        str(item.get("address")): item
        for item in state.get("bindings", [])
        if isinstance(item, dict)
    }


def resolve_slot_addresses(
    state: dict[str, Any], resolver: Callable[[str], str] | None
) -> dict[str, Any]:
    if not callable(resolver):
        return state
    cache: dict[str, str] = {}

    def resolve(name: str) -> str:
        if name not in cache:
            cache[name] = resolver(name)
        return cache[name]

    resolved = dict(state)
    resolved["messages"] = [
        {
            **message,
            "to": resolve(message["to"]),
            **(
                {"from": resolve(message["from"])}
                if isinstance(message.get("from"), str)
                else {}
            ),
        }
        if isinstance(message, dict) and isinstance(message.get("to"), str)
        else message
        for message in state.get("messages", [])
    ]
    resolved["bindings"] = [
        {**binding, "address": resolve(binding["address"])}
        if isinstance(binding, dict) and isinstance(binding.get("address"), str)
        else binding
        for binding in state.get("bindings", [])
    ]
    resolved["events"] = [
        {**event, "reader": resolve(event["reader"])}
        if isinstance(event, dict) and isinstance(event.get("reader"), str)
        else event
        for event in state.get("events", [])
    ]
    return resolved


def _note_deferred(deferred, address, reason, until) -> None:
    if not isinstance(address, str) or reason == "unbound":
        return
    deferred[address] = {
        "to": address,
        "reason": reason,
        "until": until.isoformat() if until else None,
    }


def _group_due_messages(state, now, config, events, index, bindings):
    concluded = set(state.get("concluded_addresses", []))
    leases = [item for item in state.get("leases", []) if isinstance(item, dict)]
    leased = {
        mid: item
        for item in leases
        if _time(item.get("expires_at"), now) > now
        for mid in item.get("message_ids", [])
    }
    grouped: dict[str, list[tuple[dict[str, Any], bool]]] = {}
    deferred: dict[str, dict[str, Any]] = {}
    for message in state.get("messages", []):
        if not isinstance(message, dict):
            continue
        mid, address = message.get("id"), message.get("to")
        if address in concluded:
            continue
        attempts_by_id = state.get("attempts", {})
        attempts = (
            attempts_by_id.get(str(message.get("id")), [])
            if isinstance(attempts_by_id, dict)
            else []
        )
        reason, until, urgent = _message_due(
            message, now, bindings, events, config, attempts, index
        )
        if reason is not None:
            _note_deferred(deferred, address, reason, until)
            continue
        if not isinstance(mid, str) or not isinstance(address, str) or until != now:
            continue
        if mid in leased:
            deferred[address] = {
                "to": address,
                "reason": "lease",
                "until": _time(leased[mid].get("expires_at"), now).isoformat(),
            }
            continue
        grouped.setdefault(address, []).append((message, urgent))
    return grouped, deferred


def _build_actions(grouped, deferred, bindings, now, config):
    actions: list[dict[str, Any]] = []
    for address, rows in sorted(
        grouped.items(),
        key=lambda pair: (not any(urgent for _, urgent in pair[1]), pair[0]),
    ):
        rows.sort(key=lambda row: (not row[1], _time(row[0].get("ts"), now)))
        urgent_rows = [row for row in rows if row[1]]
        chosen = (urgent_rows + [row for row in rows if not row[1]])[:20]
        if len(chosen) < len(rows):
            deferred[address] = {"to": address, "reason": "cap", "until": None}
        if len(actions) >= int(config.get("max_actions", 10)):
            deferred[address] = {"to": address, "reason": "cap", "until": None}
            continue
        wake = dict(bindings[address].get("wake_context") or {})
        wake.setdefault("harness", bindings[address].get("harness"))
        wake.setdefault("session_id", bindings[address].get("session_id"))
        wake.setdefault("cwd", bindings[address].get("cwd"))
        wake.setdefault("paseo_id", wake.pop("paseo_agent_id", None))
        ids = [str(row[0]["id"]) for row in chosen]
        stall_subjects = [
            row[0]["text"].removeprefix("Stall ").split(":", 1)[0]
            for row in chosen
            if row[0].get("from") == "runner"
            and isinstance(row[0].get("text"), str)
            and row[0]["text"].startswith("Stall ")
            and ":" in row[0]["text"]
        ]
        prompt = (
            f"[varde-delivery: pending {address}]\n"
            f"Varde messages for {address}: {', '.join(ids)}"
        )
        if stall_subjects:
            prompt += f"; stalled: {', '.join(stall_subjects)}"
        prompt += (
            "\nAcknowledge with "
            + "; ".join(
                f"`varde msg ack {message_id} --as {address}`" for message_id in ids
            )
            + "."
        )
        action = {
            "to": address,
            "address": address,
            "tier": "urgent" if urgent_rows else "regular",
            "message_ids": ids,
            "wake": wake,
            "require_idle": not bool(urgent_rows),
            "prompt": prompt,
            "urgent": bool(urgent_rows),
        }
        actions.append(action)
    return actions


def _escalations(state, events, now):
    excluded = _excluded_addresses(state)
    bound = {str(item.get("address")) for item in _bindings(state).values()}
    deadlines = undelivered_deadlines(
        state.get("messages", []),
        events,
        now,
        excluded_addresses=excluded,
        unbound_addresses={
            str(message.get("to"))
            for message in state.get("messages", [])
            if str(message.get("to")) not in bound
        },
    )
    return [
        {"to": "main", "message_id": message_id}
        for message_id, deadline in deadlines.items()
        if deadline <= now
    ]


def next_due(
    state: dict[str, Any],
    now: datetime,
    config: dict[str, Any] | None = None,
    *,
    resolve_reader: Callable[[str], str] | None = None,
) -> datetime | None:
    """Return the earliest timer that can change the plan or escalation output."""
    state = resolve_slot_addresses(state, resolve_reader)
    config = config or {}
    events = _events(state)
    state = _mark_urgent_messages(state, events)
    index = event_index(events)
    current = _plan(state, now, config, events, index)
    if current["actions"] or current["escalations"]:
        return now
    bindings = _bindings(state)
    due = _timer_candidates(state, now, config or {}, events, index, bindings)
    return min((max(now, item) for item in due), default=None)


def _timer_candidates(state, now, config, events, index, bindings):
    due: list[datetime] = []
    excluded = _excluded_addresses(state)
    deadlines = undelivered_deadlines(
        state.get("messages", []),
        events,
        now,
        excluded_addresses=excluded,
        unbound_addresses={
            str(message.get("to"))
            for message in state.get("messages", [])
            if str(message.get("to")) not in bindings
        },
    )
    due.extend(deadline for deadline in deadlines.values() if deadline > now)
    for message in state.get("messages", []):
        if not isinstance(message, dict):
            continue
        address, mid = message.get("to"), message.get("id")
        if not isinstance(address, str) or not isinstance(mid, str):
            continue
        if address not in bindings or _delivered(events, mid, address, index):
            continue
        attempts_by_id = state.get("attempts", {})
        attempts = (
            attempts_by_id.get(mid, []) if isinstance(attempts_by_id, dict) else []
        )
        _reason, until, _urgent = _message_due(
            message, now, bindings, events, config, attempts, index
        )
        if until and until > now:
            due.append(until)
        sent = _time(message.get("ts"), now)
        binding = bindings[address]
        last_seen = _time(
            binding.get("last_seen"), datetime.min.replace(tzinfo=now.tzinfo)
        )
        grace = _shifted(sent, timedelta(seconds=120), events, now, index)
        if now - last_seen <= timedelta(seconds=120) and grace > now:
            due.append(grace)
        retry = backoff_until(events, mid, attempts, index)
        if retry and retry > now:
            due.append(retry)
        pushed = receipt_pending(events, mid, index)
        if pushed:
            due.append(
                _shifted(
                    _time(pushed.get("at"), now),
                    timedelta(minutes=int(config.get("receipt_minutes", 10))),
                    events,
                    now,
                    index,
                )
            )
        if not _relay_urgent(message, bindings):
            due.append(
                _shifted(
                    sent,
                    timedelta(minutes=int(config.get("digest_minutes", 2))),
                    events,
                    now,
                    index,
                )
            )
    due.extend(
        _time(item.get("expires_at"), now)
        for item in state.get("leases", [])
        if isinstance(item, dict)
    )
    return due


def _excluded_addresses(state: dict[str, Any]) -> set[str]:
    retired = state.get("retired", {})
    return (
        set(state.get("concluded_addresses", []))
        | set(state.get("retired_addresses", []))
        | (set(retired) if isinstance(retired, dict) else set())
    )

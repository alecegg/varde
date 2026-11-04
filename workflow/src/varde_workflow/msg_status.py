"""Workflow adapters for the backend-neutral message status view."""

from __future__ import annotations

from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.views import msg_status as _view
from varde_data.views.msg_status import (
    build_report as _build_report,
)
from varde_data.views.msg_status import (
    status_messages as _status_messages,
)

from varde_workflow.relay_plan import is_urgent
from varde_workflow.relay_state import load as load_relay
from varde_workflow.slots import resolve_reader


def status_messages(inbox: Path, repository=None) -> list[dict[str, Any]]:
    if repository is None:
        repository = open_data(inbox.parent.parent, load_data_config()).messages
    # The file backend's status() also rebuilds pending and acknowledgement
    # indexes, which load_report immediately computes from these records.
    config = load_data_config()
    if config.backends.get("messages", "files") == "files":
        from varde_data.messages import below_watermark

        below = below_watermark(inbox)
    else:
        below = repository.status().diagnostics.get("below_watermark", ())
    return _status_messages(
        repository, below if isinstance(below, (list, tuple, set)) else ()
    )


def build_report(messages, deliveries, events, bindings, now, relay=None):
    return _build_report(messages, deliveries, events, bindings, now, relay, is_urgent)


def load_report(working: str, now: datetime) -> dict[str, Any]:
    root = Path(working)
    inbox = root / ".cache" / "inbox"
    state = load_relay(working)
    data = open_data(root, load_data_config())
    runner_alive = _view.runner_relay_alive(state, now)
    relay = {
        "runner_relay": "up" if runner_alive else "down",
        "leases": state.get("leases", []),
    }
    repository = data.messages
    messages = status_messages(inbox, repository)
    deliveries = [
        {
            "message_id": item.message_id,
            "reader": item.reader,
            "session": item.session,
            "via": item.via,
            "event": item.event,
            "at": item.at,
            **(
                {"action_created_at": item.action_created_at}
                if item.action_created_at
                else {}
            ),
            **({"reason": item.reason} if item.reason else {}),
            **dict(item.details),
        }
        for item in repository.deliveries()
    ]
    events = [dict(item) for item in repository.status_events()]
    bindings: list[dict[str, Any]] = [
        {
            "address": item.address,
            "session_id": item.session_id,
            "harness": item.harness,
            "bound_at": item.bound_at.isoformat(),
            "last_seen": item.last_seen.isoformat(),
            "token_id": item.token_id,
            **item.extra,
        }
        for item in data.addresses.list_bindings()
    ]
    resolve = cache(lambda reader: resolve_reader(reader, working))
    for message in messages:
        message["to"] = resolve(str(message.get("to", "")))
    for event in deliveries + events:
        if isinstance(event.get("reader"), str):
            event["reader"] = resolve(event["reader"])
    for binding in bindings:
        if isinstance(binding.get("address"), str):
            binding["address"] = resolve(str(binding["address"]))
    return build_report(messages, deliveries, events, bindings, now, relay)


# Compatibility exports used by adjacent workflow commands and status tests.
ALERT_EVENTS = _view.ALERT_EVENTS
_recent_alerts = _view._recent_alerts
banner = _view.banner
filter_retired = _view.filter_retired
find_stray_stores = _view.find_stray_stores
parse_time = _view.parse_time
percentile = _view.percentile

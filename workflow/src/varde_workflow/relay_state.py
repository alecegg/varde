"""Persistent relay leases, confirmations, mailman liveness, and escalation."""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from varde_data.views.relay_plan import RECEIPT_CAPABLE


def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).isoformat().replace("+00:00", "Z")


def record(working: str | Path, event: str, *, now: datetime, **data: object) -> None:
    """Append a relay-local lifecycle event and wake a waiting planner."""
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    # Preserve the legacy temp-file token draw so deterministic golden IDs stay stable.
    secrets.token_hex(4)
    open_data(Path(working), load_data_config()).addresses.record_event(
        event, now=now, data=data
    )


def load(working: str | Path) -> dict[str, Any]:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    data = open_data(Path(working), load_data_config())
    snapshot = data.addresses.relay_snapshot()
    return {
        "events": [dict(row) for row in snapshot.events],
        "leases": [
            {
                **item.payload,
                "action_id": item.action_id,
                "address": item.address,
                "to": item.address,
                "message_ids": list(item.message_ids),
                "token_id": item.token_id,
                "status": item.status,
                "created_at": _stamp(item.created_at),
                "expires_at": _stamp(item.expires_at),
            }
            for item in snapshot.leases
        ],
        "attempts": {
            key: [dict(row) for row in rows] for key, rows in snapshot.attempts.items()
        },
        "mailman_started": {
            key: _stamp(value) for key, value in snapshot.mailman_started.items()
        },
        "current_mailman": snapshot.current_mailman,
        "cycles": dict(snapshot.cycles),
        "retired": dict(data.addresses.retired_records()),
        "concluded_addresses": sorted(data.messages.concluded_addresses()),
    }


def mark_address_concluded(working: str | Path, address: str) -> None:
    """Persist an address that should no longer receive relay messages."""
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    open_data(Path(working), load_data_config()).messages.mark_concluded(address)


def planning_state(working: str | Path, now: datetime | None = None) -> dict[str, Any]:
    """Capture inbox state and persist expired-target transitions before planning."""
    now = now or datetime.now(UTC)
    from varde_workflow.relay_wait import _service

    return _service(working, now=lambda: now)._state() | {"working": str(working)}


def lease_actions(
    working: str | Path,
    actions: list[dict[str, Any]],
    token_id: str,
    now: datetime,
    *,
    lease_for: timedelta = timedelta(minutes=5),
    harness: str = "unknown",
) -> list[dict[str, Any]]:
    """Lease available actions and persist one receipt record per action."""
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    rows = open_data(Path(working), load_data_config()).addresses.lease_actions(
        actions, token_id, now, lease_for=lease_for, harness=harness
    )
    return [
        {
            **row.payload,
            "action_id": row.action_id,
            "address": row.address,
            "to": row.address,
            "message_ids": list(row.message_ids),
            "token_id": row.token_id,
            "status": row.status,
            "created_at": _stamp(row.created_at),
            "expires_at": _stamp(row.expires_at),
        }
        for row in rows
    ]


def action_record(working: str | Path, action_id: str) -> dict[str, Any] | None:
    """Return an action record for the hook receipt path."""
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    row = open_data(Path(working), load_data_config()).addresses.action(action_id)
    if row is None:
        return None
    return {
        **row.payload,
        "action_id": row.action_id,
        "address": row.address,
        "to": row.address,
        "message_ids": list(row.message_ids),
        "token_id": row.token_id,
        "status": row.status,
        "created_at": _stamp(row.created_at),
        "expires_at": _stamp(row.expires_at),
    }


def superseded(working: str | Path, token_id: str) -> bool:
    """Check whether the mailman current pointer has moved to another token."""
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    return open_data(Path(working), load_data_config()).addresses.superseded(token_id)


def confirm(  # noqa: PLR0913 - confirm carries result and evidence metadata.
    working: str | Path,
    action_id: str,
    result: str,
    now: datetime,
    *,
    session: str = "",
    harness: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    """Record a mailman result once, applying its per-message transitions."""
    from varde_workflow.relay_wait import _service

    return _service(working, now=lambda: now).confirm(
        action_id, result, now, session=session, harness=harness, reason=reason
    )


def renew(
    working: str | Path,
    action_id: str,
    now: datetime,
    *,
    lease_for: timedelta = timedelta(minutes=5),
) -> bool:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    return open_data(Path(working), load_data_config()).addresses.renew(
        action_id, now, lease_for=lease_for
    )


def end(working: str | Path, token_id: str, now: datetime) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    instance_id = f"{os.environ.get('PASEO_AGENT_ID', 'process')}:{os.getpid()}"
    open_data(Path(working), load_data_config()).addresses.end(
        token_id, now, instance_id=instance_id
    )


def heartbeat(
    working: str | Path,
    token_id: str,
    status: str,
    now: datetime,
    *,
    expect_return_by: datetime | None = None,
) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    instance_id = f"{os.environ.get('PASEO_AGENT_ID', 'process')}:{os.getpid()}"
    open_data(Path(working), load_data_config()).addresses.heartbeat(
        token_id,
        status,
        now,
        instance_id=instance_id,
        expect_return_by=expect_return_by,
    )


def return_mailman(  # noqa: PLR0913
    working: str | Path,
    token_id: str,
    now: datetime,
    expect_return_by: datetime,
    *,
    started: datetime | None = None,
    had_action: bool = False,
    waited: timedelta | None = None,
) -> bool:
    """Count waits that reached their deadline; early action returns are not cycles."""
    started = started or expect_return_by - timedelta(minutes=9)
    waited = waited if waited is not None else now - started
    reached_deadline = waited >= (expect_return_by - started) * 0.9
    completed = had_action or reached_deadline
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    instance_id = f"{os.environ.get('PASEO_AGENT_ID', 'process')}:{os.getpid()}"
    return open_data(Path(working), load_data_config()).addresses.return_mailman(
        token_id,
        now,
        expect_return_by,
        instance_id=instance_id,
        completed=completed,
        reached_deadline=reached_deadline,
    )


def mailman_alive(working: str | Path, token_id: str, now: datetime) -> bool:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    return open_data(Path(working), load_data_config()).addresses.mailman_alive(
        token_id, now
    )


def mailman_block(
    working: str | Path,
    token_id: str,
    now: datetime,
    *,
    context_tokens: int | None = None,
    baseline_tokens: int = 0,
) -> dict[str, Any]:
    """Return stable per-mailman liveness and recreate counters for status."""
    from varde_workflow.relay_wait import _service

    return _service(working, now=lambda: now)._mailman(token_id, now, context_tokens)


def elapsed(working: str | Path, start: datetime, end_at: datetime) -> timedelta:
    """Return wall elapsed time with recorded sleep gaps removed."""
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.views.relay_liveness import elapsed as view_elapsed

    events = (
        open_data(Path(working), load_data_config()).addresses.relay_snapshot().events
    )
    return view_elapsed(start, end_at, events)


def recreate_due(
    working: str | Path,
    now: datetime,
    *,
    token_id: str | None = None,
    context_tokens: int | None = None,
    baseline_tokens: int = 0,
) -> bool:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    data = open_data(Path(working), load_data_config())
    snapshot = data.addresses.relay_snapshot()
    token_id = token_id or snapshot.current_mailman or ""
    started_at = snapshot.mailman_started.get(token_id)
    pushed = [
        event
        for event in data.messages.deliveries()
        if event.event == "pushed"
        and event.details.get("token_id") == token_id
        and (started_at is None or event.at >= _stamp(started_at))
    ]
    age_due = bool(started_at) and elapsed(working, started_at, now) >= timedelta(
        hours=24
    )
    return (
        len(pushed) >= 15
        or age_due
        or context_tokens is not None
        and context_tokens - baseline_tokens > 40_000
    )


def suspect_due(
    working: str | Path,
    now: datetime,
    *,
    receipt_window: timedelta = timedelta(minutes=10),
) -> list[str]:
    """Mark expired pushes suspect only when their harness supports receipts."""
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.messages import RelayEvent

    data = open_data(Path(working), load_data_config())
    events = data.messages.deliveries()
    delivered = {
        (event.message_id, event.reader)
        for event in events
        if event.event == "delivered"
    }
    suspects = {
        (event.message_id, event.details.get("action_id"))
        for event in events
        if event.event == "suspect"
    }
    recorded: list[str] = []
    for event in events:
        if (
            event.event != "pushed"
            or event.details.get("harness") not in RECEIPT_CAPABLE
        ):
            continue
        mid, reader = event.message_id, event.reader
        action_id = event.details.get("action_id", "")
        if (mid, action_id) in suspects or (mid, reader) in delivered:
            continue
        pushed_at = datetime.fromisoformat(event.at)
        if elapsed(working, pushed_at, now) < receipt_window:
            continue
        if not data.addresses.reserve_suspect(f"{mid}:{action_id}", now):
            continue
        data.messages.record_relay_event(
            RelayEvent(
                mid,
                reader,
                "suspect",
                _stamp(now),
                action_created_at=event.action_created_at,
                details={"action_id": str(action_id)},
            )
        )
        recorded.append(mid)
    return recorded


def escalate_due(working: str | Path, now: datetime) -> list[str]:
    """Escalate due undelivered mail through the shared 10-minute rule."""
    from varde_workflow.relay_wait import _service

    service = _service(working, now=lambda: now)
    return service.escalate_due(now)

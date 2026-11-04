"""Workflow adapter for the shared relay service."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.relay import RelayService
from varde_data.views.relay_plan import plan

POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 30.0


def _service(
    working: str | Path,
    *,
    now: Callable[[], datetime] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> RelayService:
    data = open_data(Path(working), load_data_config())
    completed = {
        str(row.fields.get("id", Path(row.path).parent.name))
        for row in data.plans.list().records
        if row.status == "completed"
    }
    instance_id = f"{os.environ.get('PASEO_AGENT_ID', 'process')}:{os.getpid()}"
    return RelayService(
        data.addresses,
        data.messages,
        completed_plan_ids=completed,
        now=now,
        monotonic=monotonic,
        sleep=sleep,
        instance_id=instance_id,
    )


def _current_token(working: str | Path) -> str | None:
    """Return the bound mailman token through the address repository."""
    return open_data(Path(working), load_data_config()).addresses.current_token(
        "mailman"
    )


def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _workflow_response(value: dict[str, Any]) -> dict[str, Any]:
    actions = value.get("actions")
    if not isinstance(actions, list):
        return value
    ordered = []
    for action in actions:
        if not isinstance(action, dict) or "harness" not in action:
            ordered.append(action)
            continue
        fixed = {
            "action_id",
            "address",
            "to",
            "token_id",
            "harness",
            "status",
            "created_at",
            "expires_at",
            "lease_until",
            "attempt",
        }
        row: dict[str, Any] = {}
        if "to" in action:
            row["to"] = action["to"]
        row["address"] = action.get("address", action.get("to"))
        row.update(
            {
                key: item
                for key, item in action.items()
                if key not in fixed and key != "address"
            }
        )
        for key in (
            "action_id",
            "token_id",
            "harness",
            "created_at",
            "expires_at",
            "status",
            "lease_until",
            "attempt",
        ):
            if key in action:
                row[key] = action[key]
        ordered.append(row)
    return {**value, "actions": ordered}


def _response(
    working: str | Path, token_id: str, now: datetime, context_tokens: int | None
) -> dict[str, Any]:
    service = _service(working, now=lambda: now)
    state = service._state()
    planned = plan(
        state, now, service.config, resolve_reader=service.addresses.resolve_alias
    )
    return _workflow_response(
        service._response(token_id, now, state, planned, context_tokens)
    )


def once(
    working: str | Path, token_id: str, now: datetime, context_tokens: int | None = None
) -> dict[str, Any]:
    """Escalate due messages, plan once, and lease available actions."""
    service = _service(working, now=lambda: now)
    return _workflow_response(service.once(token_id, now, context_tokens))


def wait(  # noqa: PLR0913
    working: str | Path,
    token_id: str,
    timeout: float,
    *,
    now: Callable[[], datetime] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    poll: Callable[[float], None] = time.sleep,
    context_tokens: int | None = None,
) -> dict[str, Any]:
    """Wait for due work through RelayService with injectable clocks."""
    result = _service(working, now=now, monotonic=monotonic, sleep=poll).wait(
        token_id, timeout, context_tokens=context_tokens, poll=poll
    )
    return _workflow_response(result)

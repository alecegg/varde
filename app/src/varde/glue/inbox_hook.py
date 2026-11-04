"""Import-light prompt inbox adapter."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

_PROMPT_SQLITE_BUSY_TIMEOUT = 2


def prompt_inbox(
    harness: str,
    raw: bytes,
    *,
    now: datetime | None = None,
    banner_enabled: bool = True,
    surface: Literal["prompt", "stop"] = "prompt",
) -> list[str]:
    """Bind and deliver prompt inbox mail; nothing when the runner is off."""
    if not runner_on():
        return []
    return _deliver(harness, raw, now, banner_enabled, surface)


def _deliver(
    harness: str,
    raw: bytes,
    now: datetime | None,
    banner_enabled: bool,
    surface: str,
) -> list[str]:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_workflow.msg_status import banner, load_report

    try:
        payload = json.loads(raw)
    except ValueError, UnicodeDecodeError:
        return []
    if not isinstance(payload, dict) or "agent_id" in payload:
        return []
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return []

    prompt = payload.get("prompt", "")
    prompt = prompt if isinstance(prompt, str) else ""
    moment = now or datetime.now(UTC)
    cwd = Path.cwd()
    from varde_workflow.binding import resolve_working_dir

    working = resolve_working_dir(cwd)
    config = load_data_config()
    data = open_data(working, config)
    addresses = data.addresses

    # Resolve existing binding and marker first. The plan owner route remains
    # between marker redemption and the guarded environment fallback.
    environment = {**os.environ, "PWD": str(cwd)}
    reader_environment = {"PWD": str(cwd)}
    if paseo_id := os.environ.get("PASEO_AGENT_ID"):
        reader_environment["PASEO_AGENT_ID"] = paseo_id
    from varde_workflow.binding import parse_marker

    marker_parts = parse_marker(prompt)
    marker = (
        f"[varde-address: {marker_parts[0]} {marker_parts[1]}]"
        if marker_parts
        else None
    )
    # Legacy redeem used this reduced environment for identity, but read runner
    # wake metadata from os.environ internally. Keep those sources split here.
    reader = addresses.resolve_reader(
        harness,
        session_id,
        marker,
        _reader_context(reader_environment, metadata_environment=environment),
        moment,
    )
    if reader is not None:
        addresses.clear_wake_gone(reader, moment)
    if reader is None:
        reader = _owner_reader(working, harness, session_id)
    if reader is None:
        reader = addresses.resolve_reader(
            harness, session_id, None, _reader_context(environment), moment
        )
        if reader is not None:
            addresses.clear_wake_gone(reader, moment)
    if reader is None:
        return []

    claimed = _record_and_claim(working, config, prompt, reader, session_id, moment)
    if claimed is None:
        return []
    messages, delivered = claimed
    addresses.touch_wake()
    prefix = f"inbox for {reader}: " if surface == "stop" else "inbox: "
    lines = [
        f"{prefix}{message.from_} {message.kind}: {message.text}"
        + (f" (notes: {message.notes})" if message.notes is not None else "")
        for message in delivered
    ]
    if reader == "main" and banner_enabled:
        try:
            if not _claim_banner_slot(working, moment):
                return lines
            from varde_data.relay import RelayService

            RelayService(addresses, messages).escalate_due(moment)
            report = load_report(str(working), moment)
            alert = banner(report)
            if alert:
                lines.append(alert)
        except Exception:  # noqa: BLE001, S110
            pass
    return lines


def runner_on() -> bool:
    from varde_data.config import runner_enabled

    return runner_enabled()


def _bounded_messages(
    working: Path,
    config: Any,
    *,
    busy_timeout: float = _PROMPT_SQLITE_BUSY_TIMEOUT,
) -> Any:
    """Open messages with a short busy bound for the prompt path."""
    from varde_data.messages import open_messages

    return open_messages(
        working, config.backends.get("messages", "files"), busy_timeout=busy_timeout
    )


def _record_and_claim(
    working: Path,
    config: Any,
    prompt: str,
    reader: str,
    session_id: str,
    moment: datetime,
) -> tuple[Any, list[Any]] | None:
    """Record the delivery receipt and claim mail; None when a store is busy."""
    from varde_data.errors import Locked

    try:
        messages = _bounded_messages(working, config)
        _record_receipt(working, prompt, reader, session_id, moment)
        delivered = messages.claim_unread(
            reader,
            session_id,
            "hook",
            now=moment.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        )
        return messages, list(delivered)
    except Locked:
        return None


def _record_receipt(
    working: Path, prompt: str, reader: str, session_id: str, now: datetime
) -> None:
    import re

    marker_pattern = re.compile(
        r"\[varde-delivery: ([A-Za-z0-9._-]+) ([A-Za-z0-9._-]+)\]\Z"
    )
    marker = next(
        (
            match
            for line in prompt.split("\n")[:5]
            if (match := marker_pattern.fullmatch(line.removesuffix("\r")))
        ),
        None,
    )
    if marker is None:
        return

    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.messages import DeliveryOutcome, RelayEvent

    config = load_data_config()
    repository = _bounded_messages(working, config)
    addresses = open_data(working, config).addresses

    def events():
        return repository.deliveries()

    def record_event(message_id: str, target: str, event: str, **details: str) -> None:
        via = details.pop("via", "relay")
        outcome = repository.record_relay_event(
            RelayEvent(
                message_id,
                target,
                event,
                now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                session_id,
                via,
                details.pop("action_created_at", None),
                details.pop("reason", None),
                details,
            )
        )
        if outcome is DeliveryOutcome.RECORDED:
            addresses.touch_wake()
        if event == "delivered" and via in {"hook", "receipt", "read"}:
            addresses.clear_wake_gone(target, now)

    action_id, marker_address = marker.groups()
    action = addresses.action(action_id)
    if not action:
        addresses.record_event(
            "receipt-noop", now=now, data={"action_id": action_id, "reason": "unknown"}
        )
        return
    address = action.address
    if marker_address != address or reader != address:
        prior = events()
        seen: set[str] = set()
        for message_id in action.message_ids:
            if (
                not isinstance(message_id, str)
                or message_id in seen
                or any(
                    event.event == "misdelivered"
                    and event.message_id == message_id
                    and event.session == session_id
                    for event in prior
                )
            ):
                continue
            seen.add(message_id)
            record_event(
                message_id,
                reader,
                "misdelivered",
                action_id=action_id,
                address=address,
                receipt_address=marker_address,
            )
        return

    expired = action.expires_at <= now
    if expired:
        addresses.record_event(
            "receipt-noop", now=now, data={"action_id": action_id, "reason": "expired"}
        )
        return

    prior = events()
    for message_id in action.message_ids:
        already_delivered = any(
            event.message_id == message_id
            and event.reader == address
            and event.event == "delivered"
            for event in prior
        )
        if not already_delivered:
            record_event(
                message_id,
                address,
                "delivered",
                via="receipt",
                action_id=action_id,
            )


def _claim_banner_slot(working: Path, now: datetime) -> bool:
    inbox = working / ".cache" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    lock_path = inbox / ".status-banner.lock"
    stamp_path = inbox / ".status-banner"
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            previous = datetime.fromisoformat(stamp_path.read_text())
        except OSError, ValueError:
            previous = None
        if previous and now.astimezone(UTC) - previous.astimezone(UTC) < timedelta(
            minutes=10
        ):
            return False
        stamp_path.write_text(now.astimezone(UTC).isoformat())
        return True


def resolve_address(harness: str, session_id: Any) -> str | None:
    if not isinstance(session_id, str) or not session_id:
        return None
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_workflow.binding import resolve_working_dir

    cwd = Path.cwd()
    working = resolve_working_dir(cwd)
    moment = datetime.now(UTC)
    addresses = open_data(working, load_data_config()).addresses
    environment = dict(os.environ)
    reader_environment = {"PWD": environment.get("PWD", str(cwd))}
    if paseo_id := environment.get("PASEO_AGENT_ID"):
        reader_environment["PASEO_AGENT_ID"] = paseo_id
    reader = addresses.resolve_reader(
        harness,
        session_id,
        None,
        _reader_context(reader_environment, metadata_environment=environment),
        moment,
    )
    if reader is not None:
        addresses.clear_wake_gone(reader, moment)
        return reader
    owner_reader = _owner_reader(working, harness, session_id)
    if owner_reader is not None:
        return owner_reader
    reader = addresses.resolve_reader(
        harness,
        session_id,
        None,
        _reader_context(environment),
        moment,
    )
    if reader is not None:
        addresses.clear_wake_gone(reader, moment)
    return reader


def _reader_context(
    environment: dict[str, str], *, metadata_environment: dict[str, str] | None = None
):
    from varde_data.records.addresses import ReaderContext

    metadata = metadata_environment if metadata_environment is not None else environment
    return ReaderContext(
        cwd=environment.get("PWD", "."),
        paseo_id=environment.get("PASEO_AGENT_ID"),
        agent_id=metadata.get("VARDE_AGENT_ID"),
        runner_harness=metadata.get("VARDE_HARNESS"),
        runner_endpoint=metadata.get("VARDE_RUNNER_ENDPOINT"),
        env_address=environment.get("VARDE_ADDRESS"),
    )


def _owner_reader(working: Path, harness: str, session_id: str) -> str | None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    owner = f"{harness}:{session_id}"
    plans = open_data(working, load_data_config()).plans
    records = plans.owner_lookup(owner)
    if not records:
        return None
    plan = records[0]
    identifier = plan.fields.get("id")
    if isinstance(identifier, str):
        return identifier
    return Path(plan.path).parent.name or "plan"

"""Message inbox operations."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.errors import Invalid, NotFound

from varde_workflow.inbox import (
    KINDS,
    Message,
    append_event_message,
    append_message,
    claim_unread,
    commit_cursor,
    delivery_events,
    read_all,
    read_unread,
    record_delivery,
    record_relay_event,
    unread,
)
from varde_workflow.recipients import RecipientError, Resolved, resolve
from varde_workflow.urgent import urgent_send_cause


def _working_dir() -> Path:
    from varde_learn.knowledge.memory import MemoryPaths, find_root

    cwd = Path.cwd()
    root = find_root(cwd) or cwd
    return MemoryPaths.resolve(root).working.path


def _liveness_warning(token_age_s: int | None, *, has_token: bool) -> str:
    """Format the stderr warning shown when no mailman is waiting."""
    if not has_token:
        return "relay: no mailman waiting (no mailman token)"
    if token_age_s is None:
        return "relay: no mailman waiting (no heartbeat recorded)"
    return f"relay: no mailman waiting (last heartbeat {token_age_s}s ago)"


def needs_decision_notes(kind: str, to: str) -> bool:
    """Whether this message must point to decision notes."""
    return to == "main" and kind in {"merge-ready", "needs-user"}


def valid_decision_notes(path: str | Path) -> bool:
    """Accept existing notes; JSON notes must be an object (any decision type)."""
    notes = Path(path)
    if not notes.is_file():
        return False
    if notes.suffix.lower() != ".json":
        return True
    try:
        value = json.loads(notes.read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        return False
    return isinstance(value, dict)


def _resolve_recipient(name: str, working: str | Path) -> Resolved:
    """Load the address registry and resolve one send target."""
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    addresses = open_data(Path(working), load_data_config()).addresses
    return resolve(
        name,
        addresses.slots(),
        addresses.list_bindings(),
        addresses.live_addresses(datetime.now(UTC)),
    )


def _record_send_liveness(working: str | Path, message: Message) -> None:
    """Record relay liveness without making telemetry a send failure."""
    try:
        from datetime import UTC, datetime

        from varde_data.config import load_data_config
        from varde_data.open import open_data

        from varde_workflow.commands.msg_relay import _mailman_token
        from varde_workflow.relay_state import record
        from varde_workflow.send_liveness import _token_age_s

        token = _mailman_token(working)
        now = datetime.now(UTC)
        addresses = open_data(Path(working), load_data_config()).addresses
        relay_events = [dict(event) for event in addresses.relay_snapshot().events]
        token_age_s = _token_age_s(relay_events, token, now)
        alive = bool(token and addresses.mailman_alive(token, now))
        record(
            working,
            "send-liveness",
            now=now,
            message_id=message.id,
            to=message.to,
            alive=alive,
            token_age_s=token_age_s,
        )
        if not alive:
            print(
                _liveness_warning(token_age_s, has_token=bool(token)),
                file=sys.stderr,
            )
    except Exception:  # noqa: BLE001, S110 - telemetry must never fail a send
        pass


class SendError(Exception):
    """A message could not be addressed or validated."""


@dataclass(frozen=True)
class OutgoingMessage:
    from_address: str
    to: str
    kind: str
    text: str
    notes: str | Path | None = None
    reply_to: str | None = None


@dataclass(frozen=True)
class PreparedSend:
    recipient: Resolved
    role_key: str | None
    role_inbox: Any
    to: str


def prepare_send(
    to: str, kind: str, notes: str | Path | None, working: str | Path
) -> PreparedSend:
    """Resolve the recipient and validate decision notes; raise SendError."""
    role_inbox = _select_role_inbox(working)
    role_key = _role_key(to) if role_inbox is not None else None
    try:
        recipient = (
            _resolve_role_recipient(to, role_key, working)
            if role_key is not None
            else _resolve_recipient(to, working)
        )
    except RecipientError as exc:
        raise SendError(str(exc)) from exc
    address = role_key or recipient.address
    if needs_decision_notes(kind, address) and (
        not notes or not valid_decision_notes(notes)
    ):
        raise SendError(
            f"{kind} messages to main require --notes <path> "
            "naming an existing decision file"
        )
    return PreparedSend(recipient, role_key, role_inbox, address)


def append_prepared(
    prepared: PreparedSend, outgoing: OutgoingMessage, working: str | Path
) -> Message:
    """Append the message to the prepared recipient's inbox; raise SendError."""
    outgoing = replace(outgoing, to=prepared.to)
    role_key, role_inbox = prepared.role_key, prepared.role_inbox
    if role_key is not None and role_inbox is not None:
        _register_role_holders(working, role_inbox, role_key)
    try:
        if role_key is not None and role_inbox is not None:
            return _append_role_message(
                role_inbox, role_key, _new_role_message(outgoing)
            )
        return append_message(
            outgoing.from_address,
            outgoing.to,
            outgoing.kind,
            outgoing.text,
            outgoing.notes,
            working=working,
            reply_to=outgoing.reply_to,
        )
    except (ValueError, Invalid) as exc:
        raise SendError(str(exc)) from exc


def send_message(outgoing: OutgoingMessage, working: str | Path) -> Message:
    """Send one non-urgent message and record sender liveness; raise SendError."""
    prepared = prepare_send(outgoing.to, outgoing.kind, outgoing.notes, working)
    message = append_prepared(prepared, outgoing, working)
    _record_send_liveness(working, message)
    return message


def _run_send(args, working: str | Path) -> int:
    urgent = bool(getattr(args, "urgent", False))
    try:
        prepared = prepare_send(args.to, args.kind, args.notes, working)
    except SendError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    recipient, role_key, args.to = prepared.recipient, prepared.role_key, prepared.to
    if urgent:
        from varde_data.config import load_data_config
        from varde_data.open import open_data

        addresses = open_data(Path(working), load_data_config()).addresses
        events = delivery_events(working)
        cause = (
            _urgent_role_cause(
                args.from_address, role_key, recipient.address, addresses, events
            )
            if role_key is not None
            else urgent_send_cause(
                args.from_address,
                recipient.address,
                events,
                datetime.now(UTC),
                addresses.slots(),
            )
        )
        if cause:
            print(f"Error: urgent send {cause}", file=sys.stderr)
            return 1
    outgoing = OutgoingMessage(
        args.from_address, args.to, args.kind, args.text, args.notes, args.reply_to
    )
    try:
        message = append_prepared(prepared, outgoing, working)
    except SendError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if urgent:
        record_relay_event(
            working,
            message.id or "",
            message.to,
            "urgent",
            now=datetime.now(UTC),
            sender=args.from_address,
        )
    if recipient.is_role:
        state = (
            "queued"
            if args.to == "main"
            else "live"
            if recipient.has_holder
            else "no-holder"
        )
        print(f"sent {message.id} to {args.to} ({state})")
    if urgent and _is_paseo_recipient(recipient.address, working):
        print(
            "urgent delivery queued until the recipient is idle "
            "(Paseo has no mid-turn control)"
        )
    _record_send_liveness(working, message)
    return 0


def _urgent_role_cause(sender, role_key, resolved_address, addresses, events):
    from varde_data.role_inbox import role_matches_holder

    from varde_workflow.urgent import urgent_send_cause

    now = datetime.now(UTC)
    holders = [
        holder
        for holder in addresses.live_addresses(now)
        if role_matches_holder(role_key, holder)
    ] or [resolved_address]
    scoped_events = [
        {**event, "reader": resolved_address}
        if event.get("reader") == role_key
        else event
        for event in events
    ]
    return next(
        (
            cause
            for holder in holders
            if (
                cause := urgent_send_cause(
                    sender, holder, scoped_events, now, addresses.slots()
                )
            )
            is not None
        ),
        None,
    )


def _select_role_inbox(working: str | Path):
    from varde_data.role_inbox import select_role_inbox

    return select_role_inbox(Path(working))


def _role_key(address: str) -> str | None:
    from varde_data.role_inbox import role_key_for_selector

    return role_key_for_selector(address)


def _resolve_role_recipient(name: str, role_key: str, working: str | Path) -> Resolved:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.role_inbox import role_matches_holder

    addresses = open_data(Path(working), load_data_config()).addresses
    if ":" in role_key:
        resolved = _resolve_recipient(name, working)
        return Resolved(role_key, resolved.has_holder, True)
    live = addresses.live_addresses(datetime.now(UTC))
    return Resolved(
        role_key,
        any(role_matches_holder(role_key, holder) for holder in live),
        True,
    )


def _new_role_message(args):
    from varde_data.records.messages import NewMessage

    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return NewMessage(
        args.from_address,
        args.to,
        args.kind,
        args.text,
        str(args.notes) if args.notes is not None else None,
        now,
        args.reply_to,
    )


def _append_role_message(inbox, role_key: str, new_message) -> Message:
    row = inbox.append(role_key, new_message)
    return Message(
        row.ts, row.from_, row.to, row.kind, row.text, row.notes, row.id, row.reply_to
    )


def _register_role_holders(working, inbox, role_key: str) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.role_inbox import role_matches_holder

    addresses = open_data(Path(working), load_data_config()).addresses
    holders = tuple(
        holder
        for holder in addresses.live_addresses(datetime.now(UTC))
        if role_matches_holder(role_key, holder)
    )
    if holders:
        inbox.add_holders(role_key, holders, live_holders=holders)


def _is_paseo_recipient(address: str, working: str | Path) -> bool:
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    addresses = open_data(Path(working), load_data_config()).addresses
    slots = addresses.slots()
    bindings = addresses.list_bindings()
    role_inbox = _select_role_inbox(working)
    role_key = _role_key(address) if role_inbox is not None else None
    if role_key is not None:
        from varde_data.role_inbox import role_matches_holder

        return any(
            binding.harness == "paseo"
            and role_matches_holder(role_key, binding.address)
            for binding in bindings
        )
    canonical = _canonical_address(address, addresses, slots)
    return any(
        binding.harness == "paseo"
        and _canonical_address(binding.address, addresses, slots) == canonical
        for binding in bindings
    )


def _canonical_address(name, addresses, slots) -> str:
    resolved = addresses.resolve_alias(name)
    return next((slot.slot for slot in slots if slot.current_address == name), resolved)


__all__ = [
    "KINDS",
    "Message",
    "append_event_message",
    "append_message",
    "claim_unread",
    "commit_cursor",
    "delivery_events",
    "read_all",
    "read_unread",
    "record_delivery",
    "run",
    "unread",
]


def run(args, working: str | Path, *, relay_clock=None, relay_poll=None) -> int:  # noqa: PLR0911
    """Dispatch message commands from the shared CLI parser."""
    if args.message_command == "nudge":
        from varde_workflow.commands import msg_nudge

        return msg_nudge.run(args, working)
    if args.message_command in {"status", "show"}:
        from varde_workflow.commands import msg_show, msg_status

        command = msg_show if args.message_command == "show" else msg_status
        return command.run(args, working)
    if args.message_command == "migrate":
        from varde_workflow.commands import msg_migrate

        return msg_migrate.run(args, working)
    if args.message_command == "store":
        from varde_workflow.commands import msg_store

        return msg_store.run(args, working)
    if args.message_command == "relay":
        from varde_workflow.commands import msg_relay

        return msg_relay.run(args, working, wall_clock=relay_clock, poll=relay_poll)
    if args.message_command == "address":
        from varde_workflow.commands import address

        return address.run(args, working)
    if args.message_command == "ack":
        try:
            if _ack_role_message(working, args.id, args.address):
                return 0
            record_delivery(working, args.id, args.address, "acked", via="cli")
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0
    if args.message_command == "send":
        return _run_send(args, working)
    if args.message_command == "doctor":
        from varde_workflow.commands import msg_doctor

        return msg_doctor.run(args, working)
    if args.message_command == "retire":
        from varde_workflow.commands import msg_retire

        return msg_retire.run(args, working)
    if args.all:
        messages = read_all(working)
    else:
        messages = _claim_role_messages(working, args.address)
        messages.extend(claim_unread(working, args.address, "cli", "cli"))
    if args.json:
        from varde_workflow.output import print_cli_success

        print_cli_success({"messages": [item.to_dict() for item in messages]})
    else:
        for item in messages:
            print(item.line())
    return 0


def _claim_role_messages(working: str | Path, holder: str) -> list[Message]:
    inbox = _select_role_inbox(working)
    if inbox is None:
        return []
    from varde_data.role_inbox import role_keys_for_holder

    messages = []
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    for key in role_keys_for_holder(holder):
        live_holders = _live_role_holders(working, key, holder)
        inbox.add_holders(key, live_holders, live_holders=live_holders)
        messages.extend(
            Message(
                row.ts,
                row.from_,
                row.to,
                row.kind,
                row.text,
                row.notes,
                row.id,
                row.reply_to,
            )
            for row in inbox.claim_unread(key, holder, now=now)
        )
    return messages


def _live_role_holders(
    working: str | Path, role_key: str, holder: str
) -> tuple[str, ...]:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.role_inbox import role_matches_holder

    addresses = open_data(Path(working), load_data_config()).addresses
    live = addresses.live_addresses(datetime.now(UTC))
    holders = {address for address in live if role_matches_holder(role_key, address)}
    holders.add(holder)
    return tuple(sorted(holders))


def _ack_role_message(working: str | Path, message_id: str, holder: str) -> bool:
    inbox = _select_role_inbox(working)
    if inbox is None:
        return False
    from varde_data.role_inbox import role_keys_for_holder

    for key in role_keys_for_holder(holder):
        live_holders = _live_role_holders(working, key, holder)
        inbox.add_holders(key, live_holders, live_holders=live_holders)
        try:
            inbox.ack(key, holder, message_id)
        except NotFound:
            continue
        else:
            return True
    return False

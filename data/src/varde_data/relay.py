"""Relay service coordinating address and message repositories."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from varde_data.records.addresses import AddressSlot, ConfirmStatus, RelaySnapshot
from varde_data.records.messages import Message, NewMessage, RelayEvent
from varde_data.repos.addresses import AddressRepository
from varde_data.repos.messages import MessageRepository
from varde_data.views.message_receipts import undelivered_deadlines
from varde_data.views.relay_liveness import (
    HEARTBEAT_SECONDS,
    elapsed,
    mailman_alive,
)
from varde_data.views.relay_plan import (
    classify_failure,
    next_due,
    plan,
    resolve_slot_addresses,
)

POLL_SECONDS = 2.0
MAX_IDLE_POLL_SECONDS = 8.0
RECEIPT_CAPABLE = {"claude", "codex"}
MAX_ESCALATION_NOTICES = 5


class Stopped(Exception):
    """Raised when a caller requests cancellation of a relay wait."""


def _slot_aliases(slots: Iterable[AddressSlot]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for slot in slots:
        for name in (slot.slot, *slot.aliases):
            aliases.setdefault(name, slot.slot)
    return aliases


def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _sleep_gap(event: Mapping[str, object]) -> float:
    value = event.get("gap_s", 0)
    return max(0.0, float(value)) if isinstance(value, (int, float)) else 0.0


def _poll_delay(
    current: datetime,
    due: datetime | None,
    deadline: datetime,
    elapsed_mono: float,
    timeout: float,
    poll_interval: float = POLL_SECONDS,
) -> float:
    until_due = max(0.0, (due - current).total_seconds()) if due else timeout
    remaining = min(timeout + 5 - elapsed_mono, (deadline - current).total_seconds())
    delay = min(poll_interval, max(0.0, until_due), max(0.0, remaining))
    return (
        min(POLL_SECONDS, max(5.0, delay))
        if due is not None and due <= current
        else delay
    )


def _message_dict(message: Message) -> dict[str, Any]:
    return {
        "ts": message.ts,
        "from": message.from_,
        "to": message.to,
        "kind": message.kind,
        "text": message.text,
        **({"notes": message.notes} if message.notes is not None else {}),
        **({"reply_to": message.reply_to} if message.reply_to is not None else {}),
        "id": message.id,
    }


def _binding_dict(binding) -> dict[str, Any]:
    return {
        "address": binding.address,
        "session_id": binding.session_id,
        "harness": binding.harness,
        "bound_at": _stamp(binding.bound_at),
        "last_seen": _stamp(binding.last_seen),
        "token_id": binding.token_id,
        **binding.extra,
    }


def _snapshot_dict(snapshot: RelaySnapshot, concluded: set[str]) -> dict[str, Any]:
    leases = [
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
    ]
    return {
        "events": [dict(row) for row in snapshot.events],
        "leases": leases,
        "attempts": {
            key: [dict(row) for row in rows] for key, rows in snapshot.attempts.items()
        },
        "concluded_addresses": sorted(concluded),
    }


class RelayService:
    """Plan, lease, confirm, and wait for relay work across repositories."""

    def __init__(  # noqa: PLR0913 - dependencies and clocks are explicit test seams.
        self,
        addresses: AddressRepository,
        messages: MessageRepository,
        *,
        completed_plan_ids: set[str] | None = None,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        instance_id: str = "process:0",
        config: Mapping[str, Any] | None = None,
        role_inbox: Any = None,
    ):
        self.addresses = addresses
        self.messages = messages
        self.completed_plan_ids = completed_plan_ids or set()
        self.now = now or (lambda: datetime.now(UTC))
        self.monotonic = monotonic
        self.sleep = sleep
        self.instance_id = instance_id
        self.config = dict(config or {})
        self.role_inbox = role_inbox

    def _state(self) -> dict[str, Any]:
        snapshot = self.addresses.relay_snapshot()
        messages = [_message_dict(row) for row in self.messages.read_all().records]
        bindings = [_binding_dict(row) for row in self.addresses.list_bindings()]
        messages = self._role_message_views(messages, bindings)
        events = [
            {
                "event": row.event,
                "message_id": row.message_id,
                "reader": row.reader,
                "at": row.at,
                "via": row.via,
                "action_created_at": row.action_created_at,
                "reason": row.reason,
                **row.details,
            }
            for row in self.messages.deliveries()
        ]
        events.extend(dict(row) for row in snapshot.events)
        concluded = set(self.messages.concluded_addresses()) | set(
            self.completed_plan_ids
        )
        events.extend(
            {
                "event": "target-gone",
                "message_id": row.get("id"),
                "reader": row.get("to"),
                "reason": "plan-completed",
            }
            for row in messages
            if row.get("to") in concluded
        )
        state = _snapshot_dict(snapshot, concluded)
        slept = [
            event
            for event in snapshot.events
            if event.get("event") == "slept"
            and isinstance(event.get("gap_s"), (int, float))
        ]
        for lease in state["leases"]:
            created = lease.get("created_at")
            if not isinstance(created, str):
                continue
            created_at = _parse_time(created)
            removed_sleep = sum(
                _sleep_gap(event)
                for event in slept
                if created_at < _parse_time(str(event.get("at"))) <= self.now()
            )
            expires = lease.get("expires_at")
            if removed_sleep and isinstance(expires, str):
                lease["expires_at"] = _stamp(
                    _parse_time(expires) + timedelta(seconds=removed_sleep)
                )
        return {
            "messages": messages,
            "bindings": bindings,
            "retired_addresses": sorted(self.addresses.retired().addresses),
            **state,
            "events": events,
        }

    def _role_message_views(
        self, messages: list[dict[str, Any]], bindings: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if self.role_inbox is None:
            return messages
        from varde_data.role_inbox import role_key_for_selector, role_matches_holder

        live = self.addresses.live_addresses(self.now())
        message_roles = {}
        for message in messages:
            message_id = message.get("id")
            recipient = message.get("to")
            if isinstance(message_id, str) and isinstance(recipient, str):
                message_roles[message_id] = role_key_for_selector(recipient)
        role_holders: dict[str, set[str]] = {}
        for role_key in message_roles.values():
            if role_key is None:
                continue
            role_holders[role_key] = {
                str(binding["address"])
                for binding in bindings
                if isinstance(binding.get("address"), str)
                and binding["address"] in live
                and role_matches_holder(role_key, str(binding["address"]))
            }
        unread_ids: dict[tuple[str, str], set[str]] = {}
        for role_key, holders in role_holders.items():
            if holders:
                live_holders = tuple(sorted(holders))
                self.role_inbox.add_holders(
                    role_key, live_holders, live_holders=live_holders
                )
            for holder in holders:
                unread_ids[(role_key, holder)] = {
                    row.id
                    for row in self.role_inbox.unread(role_key, holder)
                    if row.id is not None
                }

        result: list[dict[str, Any]] = []
        for message in messages:
            message_id = message.get("id")
            role_key = message_roles.get(message_id)
            if role_key is None or not isinstance(message_id, str):
                result.append(message)
                continue
            holders = sorted(role_holders[role_key])
            if not holders:
                result.append(message)
                continue
            result.extend(
                {**message, "to": holder, "_shared_role_mail": True}
                for holder in holders
                if message_id in unread_ids[(role_key, holder)]
            )
        return result

    def _mailman(
        self, token_id: str, now: datetime, context_tokens: int | None = None
    ) -> dict[str, Any]:
        snapshot = self.addresses.relay_snapshot()
        events = [
            dict(event)
            for event in snapshot.events
            if event.get("token_id") == token_id
        ]
        latest = events[-1] if events else {}
        started = snapshot.mailman_started.get(token_id)
        deliveries = sum(
            event.event == "pushed"
            and event.details.get("token_id") == token_id
            and (started is None or event.at >= _stamp(started))
            for event in self.messages.deliveries()
        )
        age = elapsed(started, now, snapshot.events) if started else timedelta()
        return {
            "id": token_id,
            "alive": mailman_alive(token_id, now, snapshot.events),
            "last_heartbeat": latest.get("at")
            if latest.get("event") == "waiting"
            else None,
            "last_return": latest.get("at")
            if latest.get("event") == "returned"
            else None,
            "expect_return_by": latest.get("expect_return_by"),
            "cycles": int(snapshot.cycles.get(token_id, 0)),
            "deliveries": deliveries,
            "age_h": age.total_seconds() / 3600,
            "recreate": deliveries >= 15
            or age >= timedelta(hours=24)
            or (context_tokens is not None and context_tokens > 40_000),
        }

    def once(
        self,
        token_id: str,
        now: datetime | None = None,
        context_tokens: int | None = None,
    ) -> dict[str, Any]:
        now = now or self.now()
        state = self._state()
        self.escalate_due(now, state)
        state = self._state()
        planned = plan(
            state, now, self.config, resolve_reader=self.addresses.resolve_alias
        )
        return self._response(token_id, now, state, planned, context_tokens)

    def _response(
        self,
        token_id: str,
        now: datetime,
        state: dict[str, Any],
        planned: dict[str, Any],
        context_tokens: int | None,
    ) -> dict[str, Any]:
        actions = self.addresses.lease_actions(planned["actions"], token_id, now)
        results = []
        for action in actions:
            row = {
                **action.payload,
                "action_id": action.action_id,
                "address": action.address,
                "to": action.address,
                "message_ids": list(action.message_ids),
                "token_id": action.token_id,
                "status": action.status,
                "created_at": _stamp(action.created_at),
                "expires_at": _stamp(action.expires_at),
            }
            row["lease_until"] = row.get("expires_at")
            row["attempt"] = max(
                (
                    len(state.get("attempts", {}).get(mid, [])) + 1
                    for mid in row["message_ids"]
                ),
                default=1,
            )
            results.append(row)
        return {
            "schema": "varde-relay/1",
            "now": _stamp(now),
            "status": "actions" if results or planned["escalations"] else "none",
            "actions": results,
            "deferred": planned["deferred"],
            "escalations": planned["escalations"],
            "mailman": self._mailman(token_id, now, context_tokens),
        }

    def confirm(
        self,
        action_id: str,
        result: str,
        now: datetime | None = None,
        *,
        session: str = "",
        harness: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        now = now or self.now()
        if result not in {"pushed", "skipped-busy", "failed", "target-gone"}:
            raise ValueError(
                "result must be pushed, skipped-busy, failed, or target-gone"
            )
        start = self.addresses.begin_confirm(action_id, result, now)
        if start.status is ConfirmStatus.UNKNOWN:
            return {"status": "unknown"}
        if start.status is ConfirmStatus.DUPLICATE:
            return {"status": "duplicate"}
        action = start.action
        if action is None:
            return {"status": "unknown"}
        result = start.result or result
        accepted: list[str] = []
        delivered: list[tuple[str, str]] = []
        target_harness = harness or str(action.payload.get("harness", "unknown"))
        for message_id in action.message_ids:
            outcome = self.messages.record_relay_event(
                RelayEvent(
                    message_id,
                    action.address,
                    result,
                    _stamp(now),
                    session=session,
                    reason=(
                        (reason or result)
                        if result in {"skipped-busy", "failed", "target-gone"}
                        or reason in {"steer", "interrupt", "queued"}
                        else None
                    ),
                    action_created_at=_stamp(action.created_at),
                    details={
                        **(
                            {"harness": target_harness, "token_id": action.token_id}
                            if result == "pushed"
                            else {}
                        ),
                        **(
                            {"delivered_as": reason}
                            if reason in {"steer", "interrupt", "queued"}
                            else {}
                        ),
                        "action_id": action_id,
                    },
                )
            )
            if outcome.value in {"recorded", "duplicate"}:
                accepted.append(message_id)
                if result == "pushed" and target_harness not in RECEIPT_CAPABLE:
                    self.messages.record_relay_event(
                        RelayEvent(
                            message_id,
                            action.address,
                            "delivered",
                            _stamp(now),
                            session=session,
                            via="assumed",
                            action_created_at=_stamp(action.created_at),
                            details={"action_id": action_id},
                        )
                    )
                    delivered.append((message_id, action.address))
        if result == "target-gone":
            recent = [
                event
                for event in self.messages.deliveries()
                if event.reader == action.address
                and event.event == "target-gone"
                and elapsed(
                    _parse_time(event.at), now, self.addresses.relay_snapshot().events
                )
                <= timedelta(hours=1)
            ]
            if len(recent) >= 2:
                self.addresses.mark_wake_gone(action.address, now)
        self.addresses.finish_confirm(action_id, result, now, accepted, delivered)
        return {
            "status": "confirmed",
            "action_id": action_id,
            "result": result,
            "message_ids": accepted,
        }

    def renew(
        self,
        action_id: str,
        now: datetime | None = None,
        *,
        lease_for: timedelta = timedelta(minutes=5),
    ) -> bool:
        return self.addresses.renew(action_id, now or self.now(), lease_for=lease_for)

    def end(self, token_id: str, now: datetime | None = None) -> None:
        self.addresses.end(token_id, now or self.now(), instance_id=self.instance_id)

    def escalate_due(
        self, now: datetime, state: dict[str, Any] | None = None
    ) -> list[str]:
        state = resolve_slot_addresses(
            state or self._state(), self.addresses.resolve_alias
        )
        events = state["events"]
        excluded_addresses = set(state.get("concluded_addresses", [])) | set(
            state.get("retired_addresses", [])
        )
        bindings = {str(item.get("address")) for item in state.get("bindings", [])}
        known_addresses = set(bindings)
        for slot in self.addresses.slots():
            known_addresses.add(slot.slot)
            if slot.current_address:
                known_addresses.add(slot.current_address)
            known_addresses.update(slot.aliases)
        deadlines = undelivered_deadlines(
            state["messages"],
            events,
            now,
            excluded_addresses=excluded_addresses,
            unbound_addresses={
                str(message.get("to"))
                for message in state["messages"]
                if str(message.get("to")) not in bindings
            },
        )
        completed = {
            event.get("source_id")
            for event in events
            if event.get("event") in {"escalated", "dropped"}
        }
        prior = {
            row.get("text", "").split()[1]
            for row in state["messages"]
            if row.get("from") == "relay"
            and str(row.get("text", "")).startswith("Message m-")
        }
        due = []
        for message in state["messages"]:
            mid = message.get("id")
            if (
                not isinstance(mid, str)
                or mid in completed
                or mid in prior
                or mid not in deadlines
                or deadlines[mid] > now
            ):
                continue
            due.append(message)
        due.sort(key=lambda item: deadlines[item["id"]], reverse=True)
        if not due:
            return []

        individual = due[:MAX_ESCALATION_NOTICES]
        backlog = due[MAX_ESCALATION_NOTICES:]
        escalated: list[str] = []
        reserved_individual = self._reserve_escalations(individual, now)
        for message in reserved_individual:
            mid, recipient = message["id"], str(message["to"])
            reason = classify_failure(events, mid, recipient, bindings, known_addresses)
            self.messages.append(
                NewMessage(
                    "relay",
                    "main",
                    "info-failure",
                    f"Message {mid} to {recipient} undelivered: {reason}",
                    ts=_stamp(now),
                )
            )
            self._record_escalation(mid, recipient, reason, now)
            escalated.append(mid)

        reserved_backlog = self._reserve_escalations(backlog, now)
        if reserved_backlog:
            addresses = {str(message["to"]) for message in reserved_backlog}
            count = len(reserved_backlog)
            summary = (
                f"Older undelivered backlog summarized: {count} messages "
                f"across {len(addresses)} recipients."
            )
            self.messages.append(
                NewMessage(
                    "relay",
                    "main",
                    "info-failure",
                    summary,
                    ts=_stamp(now),
                )
            )
            escalated.extend(
                self._record_escalations(
                    reserved_backlog, events, bindings, known_addresses, now
                )
            )
        return escalated

    def _reserve_escalations(
        self, messages: list[dict[str, Any]], now: datetime
    ) -> list[dict[str, Any]]:
        reserve_many = getattr(self.addresses, "reserve_escalations", None)
        if reserve_many is None:
            return [
                message
                for message in messages
                if self.addresses.reserve_escalation(message["id"], "expired", now)
            ]
        reserved_ids = reserve_many(
            (message["id"] for message in messages), "expired", now
        )
        return [message for message in messages if message["id"] in reserved_ids]

    def _record_escalations(
        self,
        messages: list[dict[str, Any]],
        events: list[dict[str, Any]],
        bindings: set[str],
        known_addresses: set[str],
        now: datetime,
    ) -> list[str]:
        stamp = _stamp(now)
        relay_events: list[RelayEvent] = []
        audit_events: list[dict[str, object]] = []
        message_ids: list[str] = []
        failures: dict[tuple[str, str], dict[str, Any]] = {}
        for event in reversed(events):
            if event.get("event") not in {"failed", "skipped-busy", "target-gone"}:
                continue
            message_id, reader = event.get("message_id"), event.get("reader")
            if isinstance(message_id, str) and isinstance(reader, str):
                failures.setdefault((message_id, reader), event)
        for message in messages:
            message_id, recipient = message["id"], str(message["to"])
            reason = classify_failure(
                events, message_id, recipient, bindings, known_addresses, failures
            )
            relay_events.append(
                RelayEvent(
                    message_id,
                    recipient,
                    "escalated",
                    stamp,
                    reason=reason,
                    details={"source_id": message_id},
                )
            )
            audit_events.append(
                {
                    "event": "escalated",
                    "at": stamp,
                    "source_id": message_id,
                    "reason": reason,
                }
            )
            message_ids.append(message_id)
        record_many = getattr(self.messages, "record_relay_events", None)
        if record_many is None:
            for event in relay_events:
                self.messages.record_relay_event(event)
        else:
            record_many(relay_events)
        audit_many = getattr(self.addresses, "record_events", None)
        if audit_many is None:
            for row in audit_events:
                self.addresses.record_event(
                    "escalated",
                    now=now,
                    data={"source_id": row["source_id"], "reason": row["reason"]},
                )
        else:
            audit_many(audit_events)
        return message_ids

    def _record_escalation(
        self, message_id: str, recipient: str, reason: str, now: datetime
    ) -> None:
        self.messages.record_relay_event(
            RelayEvent(
                message_id,
                recipient,
                "escalated",
                _stamp(now),
                reason=reason,
                details={"source_id": message_id},
            )
        )
        self.addresses.record_event(
            "escalated",
            now=now,
            data={"source_id": message_id, "reason": reason},
        )

    def wait(  # noqa: PLR0915 - polling state machine follows workflow semantics.
        self,
        token_id: str,
        timeout: float,
        *,
        context_tokens: int | None = None,
        stop: Callable[[], bool] = lambda: False,
        poll: Callable[[float], None] | None = None,
    ) -> dict[str, Any]:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        started = self.now()
        started_mono = self.monotonic()
        deadline = started + timedelta(seconds=timeout)
        self.addresses.heartbeat(
            token_id,
            "waiting",
            started,
            instance_id=self.instance_id,
            expect_return_by=deadline,
        )
        repository_version = (self.addresses.version(), self.messages.version())
        wake_token = self.addresses.wake_token()
        due = None
        state: dict[str, Any] | None = None
        planned: dict[str, Any] | None = None
        replan = True
        poll_interval = POLL_SECONDS
        alias_lookup: dict[str, str] = {}

        def resolve_reader(name: str) -> str:
            return alias_lookup.get(name, name)

        last_poll = last_heartbeat = started
        while True:
            current = self.now()
            if stop():
                raise Stopped()
            gap = current - last_poll
            if gap > timedelta(seconds=10) and state and state.get("leases"):
                self.addresses.record_event(
                    "slept", now=current, data={"gap_s": gap.total_seconds()}
                )
            last_poll = current
            if self.addresses.superseded(token_id):
                self.end(token_id, current)
                return {
                    "schema": "varde-relay/1",
                    "now": _stamp(current),
                    "status": "superseded",
                    "mailman": self._mailman(token_id, current, context_tokens),
                }
            current_version = (self.addresses.version(), self.messages.version())
            current_wake = self.addresses.wake_token()
            should_replan = (
                replan
                or current_version != repository_version
                or current_wake != wake_token
                or (due is not None and current >= due)
            )
            if should_replan:
                self.escalate_due(current)
                state = self._state()
                alias_lookup = _slot_aliases(self.addresses.slots())
                planned = plan(
                    state,
                    current,
                    self.config,
                    resolve_reader=resolve_reader,
                )
                due = next_due(
                    state,
                    current,
                    self.config,
                    resolve_reader=resolve_reader,
                )
                repository_version = (self.addresses.version(), self.messages.version())
                wake_token = self.addresses.wake_token()
                replan = False
                poll_interval = POLL_SECONDS
            if planned is None:
                raise RuntimeError("wait plan was not initialized")
            if planned["actions"] or planned["escalations"]:
                if state is None:
                    raise RuntimeError("wait state was not initialized")
                result = self._response(
                    token_id, current, state, planned, context_tokens
                )
                if result["actions"] or result["escalations"]:
                    waited = max(0.0, (current - started).total_seconds())
                    reached_deadline = waited >= timeout * 0.9
                    self.addresses.return_mailman(
                        token_id,
                        current,
                        deadline,
                        instance_id=self.instance_id,
                        completed=True,
                        reached_deadline=reached_deadline,
                    )
                    result["mailman"] = self._mailman(token_id, current, context_tokens)
                    return result
            elapsed_mono = max(0.0, self.monotonic() - started_mono)
            if current >= deadline or elapsed_mono >= timeout + 5:
                waited = min(timeout, max(0.0, (current - started).total_seconds()))
                reached_deadline = current - started >= (deadline - started) * 0.9
                self.addresses.return_mailman(
                    token_id,
                    current,
                    deadline,
                    instance_id=self.instance_id,
                    completed=reached_deadline,
                    reached_deadline=reached_deadline,
                )
                return {
                    "schema": "varde-relay/1",
                    "now": _stamp(current),
                    "status": "none",
                    "waited_s": waited,
                    "mailman": self._mailman(token_id, current, context_tokens),
                }
            if current - last_heartbeat >= timedelta(seconds=HEARTBEAT_SECONDS):
                self.addresses.heartbeat(
                    token_id,
                    "waiting",
                    current,
                    instance_id=self.instance_id,
                    expect_return_by=deadline,
                )
                last_heartbeat = current
            delay = _poll_delay(
                current, due, deadline, elapsed_mono, timeout, poll_interval
            )
            if stop():
                raise Stopped()
            (poll or self.sleep)(delay)
            if should_replan:
                poll_interval = POLL_SECONDS
            else:
                poll_interval = min(MAX_IDLE_POLL_SECONDS, poll_interval * 2)

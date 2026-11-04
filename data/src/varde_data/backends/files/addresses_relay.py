"""File-backed relay state and action records."""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.backends.memory.addresses import MemoryAddresses, _stamp
from varde_data.locking import atomic_write, file_lock
from varde_data.records.addresses import ConfirmStatus, RelayAction

_UNKNOWN_EVENT = "_varde_raw_event"
_WAKE_AFTER = {
    "record_event",
    "record_send_liveness",
    "finish_confirm",
    "renew",
    "heartbeat",
    "heartbeat_if_waiting",
    "end",
    "return_mailman",
    "retire",
    "unretire",
    "touch_wake",
}


class FilesRelay:
    """Persist the memory repository's relay transitions under the relay lock."""

    inbox: Path
    address_root: Path

    def _relay(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "lease_actions" and args:
            args = (tuple(args[0]), *args[1:])
        root = self.inbox / "relay"
        root.mkdir(parents=True, exist_ok=True)
        with _relay_lock(root):
            state = MemoryAddresses()
            self._load_relay(state, root, _actions_for(name, args, root))
            before = self._relay_copy(state)
            if name == "renew" and args:
                action = state._actions.get(str(args[0]))
                if action is not None and action.status == "leased":
                    # Legacy renew operated on action files even when state.json
                    # had no matching lease row.
                    state._leases.add(action.action_id)
            if name == "record_send_liveness":
                result = self._record_send_liveness(state, *args, **kwargs)
            elif name == "finish_confirm":
                result = self._finish_confirm(state, root, *args, **kwargs)
            else:
                result = getattr(state, name)(*args, **kwargs)
            self._remember_candidate_order(state, name, args, result)
            operation = (
                "record_event_slept"
                if name == "record_event" and args and args[0] == "slept"
                else name
            )
            self._persist_relay(state, before, root, operation)
            should_wake = name in _WAKE_AFTER or (
                name == "begin_confirm"
                and getattr(result, "status", None) is ConfirmStatus.UNKNOWN
            )
            if should_wake and (name != "heartbeat_if_waiting" or result):
                (root / "relay.wake").touch()
            return result

    def _relay_read(self, name: str, *args: Any, **kwargs: Any) -> Any:
        state = MemoryAddresses()
        root = self.inbox / "relay"
        if name == "action":
            row = _read(root / "actions" / f"{args[0]}.json")
            return _decode_action(row, str(args[0]))
        self._load_relay(state, root, _actions_for(name, args, root))
        return getattr(state, name)(*args, **kwargs)

    def _record_send_liveness(
        self, state: MemoryAddresses, message_id: str, recipient: str, now: datetime
    ) -> None:
        current = _read(self.address_root / "mailman" / "current")
        token = current.get("token_id")
        token = token if isinstance(token, str) else None
        token_events = (
            [event for event in state._relay_events if event.get("token_id") == token]
            if token
            else []
        )
        latest = token_events[-1] if token_events else None
        age = _elapsed_seconds(state._relay_events, latest, now) if latest else None
        token_age = _elapsed_seconds(token_events, latest, now) if latest else None
        alive = bool(
            latest
            and (
                latest.get("event") == "waiting"
                and age is not None
                and age < 90
                or latest.get("event") == "returned"
                and age is not None
                and age < 300
            )
        )
        state.record_event(
            "send-liveness",
            now=now,
            data={
                "message_id": message_id,
                "to": recipient,
                "alive": alive,
                "token_age_s": token_age,
            },
        )

    @staticmethod
    def _finish_confirm(  # noqa: PLR0913, PLR0917 - repo confirmation contract.
        state: MemoryAddresses,
        root: Path,
        action_id: str,
        result: str,
        now: datetime,
        accepted_ids: Iterable[str],
        delivered: Iterable[tuple[str, str]],
    ) -> None:
        action = state._actions[action_id]
        accepted_rows = tuple(accepted_ids)
        accepted = set(accepted_rows)
        delivered_set = set(delivered)
        state._actions[action_id] = replace(
            action,
            status="confirmed",
            payload={
                **action.payload,
                "result": result,
                "confirmed_at": _stamp(now),
            },
        )
        state._leases.discard(action_id)
        if result in {"skipped-busy", "failed", "target-gone"}:
            for message_id in accepted_rows:
                rows = state._attempts.setdefault(message_id, [])
                if not any(row.get("action_id") == action_id for row in rows):
                    rows.append(
                        {"result": result, "at": _stamp(now), "action_id": action_id}
                    )
        raw = state.__dict__["_file_raw_state"]
        leases = raw.get("leases", [])
        updated: list[object] = []
        live_ids: set[str] = set()
        for lease in leases if isinstance(leases, list) else []:
            if not isinstance(lease, dict):
                updated.append(lease)
                continue
            other_id = str(lease.get("action_id", ""))
            if other_id == action_id:
                continue
            address = str(lease.get("address", ""))
            message_ids = lease.get("message_ids", [])
            remaining = [
                message_id
                for message_id in message_ids
                if message_id not in accepted
                and (message_id, address) not in delivered_set
            ]
            row = lease
            if remaining != message_ids:
                row = {**lease, "message_ids": remaining}
                other_path = root / "actions" / f"{other_id}.json"
                other_action = _read(other_path)
                other_action["message_ids"] = remaining
                if not remaining:
                    other_action["status"] = "superseded"
                _write_if_changed(other_path, other_action, 0o644)
            if remaining:
                updated.append(row)
                live_ids.add(other_id)
        raw["leases"] = updated
        state._leases = live_ids

    @staticmethod
    def _remember_candidate_order(
        state: MemoryAddresses, name: str, args: tuple[Any, ...], result: Any
    ) -> None:
        if name != "lease_actions":
            return
        candidates = args[0]
        for action in result:
            candidate = next(
                (
                    row
                    for row in candidates
                    if str(row.get("to", row.get("address", ""))) == action.address
                    and set(action.message_ids).issubset(
                        {str(mid) for mid in row.get("message_ids", [])}
                    )
                ),
                {},
            )
            state.__dict__["_file_action_order"][action.action_id] = tuple(candidate)

    @staticmethod
    def _relay_copy(state: MemoryAddresses) -> dict[str, Any]:
        return {
            key: copy.deepcopy(getattr(state, key))
            for key in (
                "_actions",
                "_leases",
                "_relay_events",
                "_attempts",
                "_escalations",
                "_suspects",
                "_started",
                "_cycles",
                "_instances",
                "_current_mailman",
                "_retired_addresses",
                "_retired_tokens",
                "_retired_at",
            )
        }

    @staticmethod
    def _load_relay(
        state: MemoryAddresses, root: Path, action_ids: Sequence[str]
    ) -> None:
        raw = _read(root / "state.json")
        state.__dict__["_file_raw_state"] = raw
        state.__dict__["_file_action_order"] = {}
        state._relay_events = [
            row if isinstance(row, dict) else {_UNKNOWN_EVENT: row}
            for row in raw.get("events", [])
        ]
        state._attempts = {
            str(key): value
            for key, value in raw.get("attempts", {}).items()
            if isinstance(value, list)
        }
        state._started = {
            str(key): stamp
            for key, value in raw.get("mailman_started", {}).items()
            if (stamp := _date(value)) is not None
        }
        state._cycles = {str(k): int(v) for k, v in raw.get("cycles", {}).items()}
        state._instances = {
            str(k): str(v) for k, v in raw.get("mailman_instances", {}).items()
        }
        state._current_mailman = (
            raw.get("current_mailman")
            if isinstance(raw.get("current_mailman"), str)
            else None
        )
        retired = raw.get("retired", {})
        state._retired_at = (
            {
                key: value
                for key, value in retired.items()
                if isinstance(key, str) and isinstance(value, str)
            }
            if isinstance(retired, dict)
            else {}
        )
        state._retired_addresses = set(raw.get("retired_addresses", [])) | {
            key for key in state._retired_at if not key.startswith("mailman:")
        }
        state._retired_tokens = set(raw.get("retired_tokens", [])) | {
            key.removeprefix("mailman:")
            for key in state._retired_at
            if key.startswith("mailman:")
        }
        state._escalations = {
            str(k): v
            for k, v in raw.get("escalations", {}).items()
            if isinstance(v, dict)
        }
        state._suspects = set(raw.get("suspects", []))
        for action_id in action_ids:
            path = root / "actions" / f"{action_id}.json"
            row = _read(path)
            action = _decode_action(row, action_id)
            if action is None:
                continue
            state.__dict__["_file_action_order"][action_id] = tuple(row)
            payload = {
                k: v
                for k, v in row.items()
                if k
                not in {
                    "action_id",
                    "address",
                    "message_ids",
                    "token_id",
                    "status",
                    "created_at",
                    "expires_at",
                }
            }
            state._actions[action_id] = RelayAction(
                action.action_id,
                action.address,
                action.message_ids,
                action.token_id,
                action.status,
                action.created_at,
                action.expires_at,
                payload,
            )
        lease_order = [
            str(row.get("action_id"))
            for row in raw.get("leases", [])
            if isinstance(row, dict) and isinstance(row.get("action_id"), str)
        ]
        state._leases = set(lease_order)
        ordered_ids = [key for key in lease_order if key in state._actions]
        ordered_ids.extend(key for key in state._actions if key not in ordered_ids)
        state._actions = {key: state._actions[key] for key in ordered_ids}

    @staticmethod
    def _persist_relay(
        state: MemoryAddresses,
        before: dict[str, Any],
        root: Path,
        operation: str,
    ) -> None:
        changed_actions = set(before["_actions"]) | set(state._actions)
        action_root = root / "actions"
        for action_id in changed_actions:
            old, action = (
                before["_actions"].get(action_id),
                state._actions.get(action_id),
            )
            if old == action:
                continue
            path = action_root / f"{action_id}.json"
            if action is None:
                path.unlink(missing_ok=True)
                continue
            action_root.mkdir(parents=True, exist_ok=True)
            value = FilesRelay._action_row(
                action, state.__dict__["_file_action_order"].get(action_id)
            )
            _write_if_changed(path, value, 0o644)
        if before == FilesRelay._relay_copy(state):
            if operation == "lease_actions" and not state._leases:
                raw_state = state.__dict__["_file_raw_state"]
                if raw_state.get("leases") != []:
                    raw_state["leases"] = []
                    _write_if_changed(root / "state.json", raw_state, 0o644)
            if operation in {"retire", "unretire"}:
                _write_if_changed(
                    root / "state.json",
                    state.__dict__["_file_raw_state"],
                    0o644,
                    force=True,
                )
            return
        raw = state.__dict__["_file_raw_state"]
        value: dict[str, object] = dict(raw)
        events = [
            row[_UNKNOWN_EVENT] if set(row) == {_UNKNOWN_EVENT} else row
            for row in state._relay_events
        ]
        leases = _serialized_leases(state, raw, operation)
        fields = _fields_for(operation, state, before, events, leases)
        for public_name, serialized in fields:
            value[public_name] = serialized
        _write_if_changed(root / "state.json", value, 0o644)

    @staticmethod
    def _action_row(
        action: RelayAction, original_order: Sequence[str] | None = None
    ) -> dict[str, object]:
        values = dict(action.payload)
        values.update(
            action_id=action.action_id,
            address=action.address,
            to=action.address,
            message_ids=list(action.message_ids),
            token_id=action.token_id,
            harness=str(action.payload.get("harness", "unknown")),
            created_at=_stamp(action.created_at),
            expires_at=_stamp(action.expires_at),
            status=action.status,
        )
        order = list(original_order or action.payload)
        row = {key: values[key] for key in order if key in values}
        for key in (
            "action_id",
            "address",
            "to",
            "message_ids",
            "token_id",
            "harness",
            "created_at",
            "expires_at",
            "status",
        ):
            row[key] = values[key]
        for key, value in values.items():
            if key not in row:
                row[key] = value
        return row

    def record_send_liveness(
        self, message_id: str, recipient: str, now: datetime
    ) -> None:
        self._relay("record_send_liveness", message_id, recipient, now)

    def record_events(self, events: Iterable[Mapping[str, object]]) -> None:
        self._relay("record_events", tuple(events))

    def reserve_escalations(
        self, keys: Iterable[str], outcome: str, now: datetime
    ) -> set[str]:
        return self._relay("reserve_escalations", tuple(keys), outcome, now)

    def superseded(self, token_id: str) -> bool:
        current = _read(self.address_root / "mailman" / "current")
        return current.get("token_id") != token_id


def _relay_dispatch(name: str):
    reader = name in {
        "relay_snapshot",
        "mailman_alive",
        "action",
        "retired",
        "retired_records",
    }

    def dispatch(self: FilesRelay, *args: Any, **kwargs: Any) -> Any:
        method = self._relay_read if reader else self._relay
        return method(name, *args, **kwargs)

    dispatch.__name__ = name
    return dispatch


for _name in (
    "relay_snapshot",
    "record_event",
    "record_events",
    "lease_actions",
    "begin_confirm",
    "finish_confirm",
    "renew",
    "end",
    "heartbeat",
    "heartbeat_if_waiting",
    "return_mailman",
    "mailman_alive",
    "action",
    "reserve_escalation",
    "reserve_escalations",
    "reserve_suspect",
    "retire",
    "unretire",
    "retired",
    "retired_records",
    "touch_wake",
):
    setattr(FilesRelay, _name, _relay_dispatch(_name))


def _date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: FURB162
    except ValueError:
        return None


def _actions_for(name: str, args: tuple[Any, ...], root: Path) -> list[str]:
    if name == "action":
        return [str(args[0])] if args else []
    if name in {"lease_actions", "relay_snapshot"} or (
        name == "record_event" and args and args[0] == "slept"
    ):
        return _lease_ids(_read(root / "state.json"))
    if name in {"begin_confirm", "finish_confirm", "renew"} and args:
        return [str(args[0])]
    return []


def _lease_ids(state: dict[str, Any]) -> list[str]:
    leases = state.get("leases", [])
    return [
        str(row["action_id"])
        for row in leases
        if isinstance(row, dict) and isinstance(row.get("action_id"), str)
    ]


def _serialized_leases(
    state: MemoryAddresses, raw: dict[str, Any], operation: str
) -> list[object]:
    original = raw.get("leases", [])
    if operation not in {
        "lease_actions",
        "renew",
        "finish_confirm",
        "record_event_slept",
    }:
        return original if isinstance(original, list) else []
    rows: list[object] = []
    old_ids: set[str] = set()
    for old_row in original if isinstance(original, list) else []:
        if not isinstance(old_row, dict) or not isinstance(
            old_row.get("action_id"), str
        ):
            continue
        action_id = str(old_row["action_id"])
        old_ids.add(action_id)
        if action_id not in state._leases:
            continue
        action = state._actions.get(action_id)
        if action is None or operation == "lease_actions":
            rows.append(old_row)
            continue
        rows.append(FilesRelay._action_row(action, tuple(old_row)))
    for action_id, action in state._actions.items():
        if action_id in old_ids or action_id not in state._leases:
            continue
        rows.append(
            FilesRelay._action_row(
                action, state.__dict__["_file_action_order"].get(action_id)
            )
        )
    return rows


def _fields_for(  # noqa: PLR0911 - branch order is disk key order.
    operation: str,
    state: MemoryAddresses,
    before: dict[str, Any],
    events: list[object],
    leases: list[object],
) -> list[tuple[str, object]]:
    if operation in {"heartbeat", "heartbeat_if_waiting", "end"}:
        return [
            ("current_mailman", state._current_mailman),
            (
                "mailman_started",
                {key: _stamp(value) for key, value in state._started.items()},
            ),
            ("mailman_instances", state._instances),
            ("events", events),
        ]
    if operation in {"record_event", "record_send_liveness", "record_events"}:
        return [("events", events)]
    if operation == "record_event_slept":
        return [("events", events), ("leases", leases)]
    if operation in {"lease_actions", "renew"}:
        return [("leases", leases)]
    if operation == "begin_confirm":
        return (
            [("events", events)]
            if before["_relay_events"] != state._relay_events
            else []
        )
    if operation == "finish_confirm":
        fields: list[tuple[str, object]] = []
        if before["_attempts"] != state._attempts:
            fields.append(("attempts", state._attempts))
        fields.append(("leases", leases))
        return fields
    if operation == "return_mailman":
        return [("cycles", state._cycles), ("events", events)]
    if operation in {"reserve_escalation", "reserve_escalations"}:
        return [("events", events), ("escalations", state._escalations)]
    if operation == "reserve_suspect":
        return [("suspects", sorted(state._suspects))]
    if operation in {"retire", "unretire"}:
        return [
            ("retired", state._retired_at),
        ]
    return []


def _relay_lock(root: Path):
    path = root / ".lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        os.fchmod(descriptor, 0o644)
    finally:
        os.close(descriptor)
    return file_lock(path, timeout=30)


def _decode_action(row: dict[str, Any], action_id: str) -> RelayAction | None:
    if not row:
        return None
    # The old workflow accepted actions without lease timestamps for confirm.
    created = _date(row.get("created_at")) or datetime.min.replace(tzinfo=UTC)
    expires = _date(row.get("expires_at")) or datetime.max.replace(tzinfo=UTC)
    ids = tuple(str(item) for item in row.get("message_ids", []))
    payload = {
        key: value
        for key, value in row.items()
        if key
        not in {
            "action_id",
            "address",
            "message_ids",
            "token_id",
            "status",
            "created_at",
            "expires_at",
        }
    }
    return RelayAction(
        str(row.get("action_id", action_id)),
        str(row.get("address", "")),
        ids,
        str(row.get("token_id", "")),
        str(row.get("status", "leased")),
        created,
        expires,
        payload,
    )


def _elapsed_seconds(
    events: Sequence[Mapping[str, object]], latest: object, now: datetime
) -> int | None:
    if not isinstance(latest, Mapping):
        return None
    stamp = _date(latest.get("at"))
    if stamp is None:
        return None
    asleep = 0.0
    for event in events:
        if event.get("event") != "slept":
            continue
        sleep_at = _date(event.get("at"))
        gap = event.get("gap_seconds", 0)
        if (
            sleep_at is not None
            and isinstance(gap, (int, float))
            and stamp < sleep_at <= now
        ):
            asleep += max(0, gap)
    return max(0, int((now - stamp).total_seconds() - asleep))


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except OSError, ValueError:
        return {}


def _write_if_changed(
    path: Path, value: object, mode: int, *, force: bool = False
) -> None:
    encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
    if not force and path.exists() and path.read_bytes() == encoded:
        return
    atomic_write(path, encoded, mode=mode)

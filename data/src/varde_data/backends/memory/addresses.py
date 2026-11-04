"""In-memory address repository used by contracts and ephemeral callers."""

from __future__ import annotations

import base64
import copy
import hashlib
import re
import secrets
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from varde_data.records.addresses import (
    AddressBinding,
    AddressEvent,
    AddressSlot,
    ConfirmStart,
    ConfirmStatus,
    ReaderContext,
    RelayAction,
    RelaySnapshot,
    Retirement,
)
from varde_data.version import Version
from varde_data.views.relay_liveness import mailman_alive as is_mailman_alive

_NAME = re.compile(r"[A-Za-z0-9._-]{1,64}\Z", re.ASCII)
_SLOT = re.compile(r"[A-Za-z0-9._-]+\Z", re.ASCII)
_MARKER = re.compile(
    r"\[varde-address: ([A-Za-z0-9._-]{1,64}) (vt1\.[A-Z2-7]{26})\]\Z", re.ASCII
)


@dataclass(frozen=True)
class _Token:
    token_id: str
    address: str
    digest: str
    issued_at: datetime
    expires_at: datetime
    uses_left: int
    supersede: bool
    issuer: str


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _session_key(harness: str, session_id: str) -> str:
    return f"{harness}-{hashlib.sha256(session_id.encode()).hexdigest()}"


class MemoryAddresses:
    """Thread-safe contract backend; every write and snapshot uses one lock."""

    def __init__(self) -> None:
        self._bindings: dict[str, AddressBinding] = {}
        self._current_sessions: dict[str, str] = {}
        self._current_tokens: dict[str, str] = {}
        self._tokens: dict[str, _Token] = {}
        self._markers: dict[str, str] = {}
        self._events: list[AddressEvent] = []
        self._slots: dict[str, AddressSlot] = {}
        self._actions: dict[str, RelayAction] = {}
        self._leases: set[str] = set()
        self._relay_events: list[Mapping[str, object]] = []
        self._attempts: dict[str, list[Mapping[str, object]]] = {}
        self._escalations: dict[str, Mapping[str, object]] = {}
        self._suspects: set[str] = set()
        self._started: dict[str, datetime] = {}
        self._cycles: dict[str, int] = {}
        self._instances: dict[str, str] = {}
        self._current_mailman: str | None = None
        self._retired_addresses: set[str] = set()
        self._retired_tokens: set[str] = set()
        self._retired_at: dict[str, str] = {}
        self._revision = 0
        self._wake_revision = 0
        self._lock = threading.RLock()

    def _write(self, *, wake: bool = False) -> None:
        self._revision += 1
        if wake:
            self._wake_revision += 1

    def _event(
        self,
        event: str,
        now: datetime,
        address: str | None = None,
        *,
        session_key: str | None = None,
        token_id: str | None = None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self._events.append(
            AddressEvent(
                event=event,
                at=now,
                address=address,
                token_id=token_id,
                session_key=session_key,
                details=dict(details or {}),
            )
        )

    def _binding_key(self, address: str) -> str | None:
        return self._current_sessions.get(address)

    def _live(self, address: str, now: datetime) -> bool:
        binding = self.current_binding(address)
        return binding is not None and now - binding.last_seen < timedelta(minutes=30)

    def issue(
        self,
        address: str,
        *,
        ttl: timedelta = timedelta(hours=24),
        uses: int = 1,
        supersede: bool = False,
        now: datetime,
        issuer: str = "unknown",
    ) -> str:
        if not _NAME.fullmatch(address):
            raise ValueError("invalid address name")
        if ttl <= timedelta(0) or uses <= 0:
            raise ValueError("ttl and uses must be positive")
        with self._lock:
            live = self._live(address, now)
            if address == "mailman" and not supersede:
                token_id = self._current_tokens.get(address)
                if token_id and is_mailman_alive(token_id, now, self._relay_events):
                    self._event(
                        "refuse", now, address, details={"reason": "mailman-alive"}
                    )
                    self._write()
                    raise ValueError("mailman address is held by a live mailman")
            if (address == "main" or (live and address != "mailman")) and not supersede:
                self._event(
                    "refuse", now, address, details={"reason": "supersede-required"}
                )
                self._write()
                raise ValueError("address requires --supersede")
            return self._mint(address, ttl, uses, supersede, now, issuer)

    def _mint(
        self,
        address: str,
        ttl: timedelta,
        uses: int,
        supersede: bool,
        now: datetime,
        issuer: str,
    ) -> str:
        for token_id, token in tuple(self._tokens.items()):
            if token.address == address and (
                now >= token.expires_at or token.uses_left == 0
            ):
                del self._tokens[token_id]
        secret = "vt1." + base64.b32encode(secrets.token_bytes(16)).decode(
            "ascii"
        ).rstrip("=")
        token_id = secrets.token_hex(8)
        self._tokens[token_id] = _Token(
            token_id,
            address,
            hashlib.sha256(secret.encode()).hexdigest(),
            now,
            now + ttl,
            uses,
            supersede,
            issuer,
        )
        self._markers[secret] = token_id
        self._write()
        return f"[varde-address: {address} {secret}]"

    def redeem(
        self,
        marker: str,
        session_id: str,
        harness: str,
        context: ReaderContext,
        *,
        now: datetime,
    ) -> bool:
        match = _MARKER.fullmatch(marker)
        if match is None:
            return False
        address, secret = match.groups()
        key = _session_key(harness, session_id)
        with self._lock:
            token_id = self._markers.get(secret)
            token = self._tokens.get(token_id or "")
            if token is None or token.address != address:
                self._event("refuse", now, address, details={"reason": "invalid-token"})
                self._write()
                return False
            current = self._bindings.get(address)
            if (
                current
                and current.token_id == token.token_id
                and self._current_sessions.get(address) == key
            ):
                self._refresh_binding(current, harness, session_id, context, now)
                self._touch_binding(address, now)
                return True
            if token.uses_left <= 0:
                self._event("token-reuse", now, address, token_id=token.token_id)
                self._write()
                return False
            if now >= token.expires_at:
                self._event("refuse", now, address, details={"reason": "expired-token"})
                self._write()
                return False
            prior_live = current is not None and self._live(address, now)
            if prior_live and current and current.session_id != session_id:
                if not token.supersede:
                    self._event(
                        "refuse", now, address, details={"reason": "live-binding"}
                    )
                    self._write()
                    return False
                self._event("supersede", now, address, details={"prior_live": True})
            elif current and current.session_id != session_id:
                self._event("supersede", now, address, details={"prior_live": False})
            has_runner_context = bool(context.agent_id and context.runner_harness)
            is_runner_binding = context.runner_binding and has_runner_context
            wake_context: dict[str, object] = {
                "harness": context.runner_harness if has_runner_context else harness,
                "session_id": session_id,
                "cwd": context.cwd,
            }
            if not is_runner_binding:
                wake_context["paseo_id"] = context.paseo_id or ""
            if has_runner_context:
                wake_context["agent_id"] = context.agent_id
                if context.runner_endpoint:
                    wake_context["runner_endpoint"] = context.runner_endpoint
            binding = AddressBinding(
                address,
                session_id,
                harness,
                now,
                now,
                token.token_id,
                {
                    **context.extra,
                    **({"runner_binding": True} if is_runner_binding else {}),
                    **({"parent_id": context.parent_id} if context.parent_id else {}),
                    "cwd": context.cwd,
                    "wake_context": wake_context,
                },
            )
            self._bindings[address] = binding
            self._current_sessions[address] = key
            self._current_tokens[address] = token.token_id
            self._tokens[token.token_id] = replace(token, uses_left=token.uses_left - 1)
            self._event("bind", now, address, session_key=key, token_id=token.token_id)
            self._write()
            return True

    def marker_error(self, marker: str, now: datetime) -> str:
        match = _MARKER.fullmatch(marker)
        if not match:
            return "unknown marker"
        address, secret = match.groups()
        with self._lock:
            token = self._tokens.get(self._markers.get(secret, ""))
        if token is None or token.address != address:
            return "unknown marker"
        if token.uses_left <= 0:
            return "marker already used"
        if now >= token.expires_at:
            return "marker expired"
        current = self._bindings.get(address)
        if current and current.token_id != token.token_id:
            return "marker superseded by a newer marker"
        return "live binding refuses this marker"

    def _refresh_binding(
        self,
        binding: AddressBinding,
        harness: str,
        session_id: str,
        context: ReaderContext,
        now: datetime,
    ) -> bool:
        if not (context.paseo_id or context.agent_id):
            return False
        wake = binding.extra.get("wake_context")
        wake_context = dict(wake) if isinstance(wake, Mapping) else {}
        has_runner_context = bool(context.agent_id and context.runner_harness)
        is_runner_binding = context.runner_binding and has_runner_context
        preserve_runner_context = bool(binding.extra.get("runner_binding")) and (
            not has_runner_context or wake_context.get("agent_id") != context.agent_id
        )
        if preserve_runner_context:
            target_harness = wake_context.get("harness", harness)
        elif is_runner_binding or has_runner_context:
            target_harness = context.runner_harness
        else:
            target_harness = harness
        updated = {
            **wake_context,
            "harness": target_harness,
            "session_id": session_id,
            "cwd": wake_context.get("cwd", context.cwd)
            if preserve_runner_context
            else context.cwd,
        }
        if is_runner_binding or binding.extra.get("runner_binding"):
            updated.pop("paseo_id", None)
        elif context.paseo_id:
            updated["paseo_id"] = context.paseo_id
        if has_runner_context and not preserve_runner_context:
            updated["agent_id"] = context.agent_id
            if context.runner_endpoint:
                updated["runner_endpoint"] = context.runner_endpoint
            else:
                updated.pop("runner_endpoint", None)
        elif not preserve_runner_context:
            updated.pop("agent_id", None)
            updated.pop("runner_endpoint", None)
        changed = (
            updated != wake_context
            or any(
                binding.extra.get(key) != value for key, value in context.extra.items()
            )
            or (is_runner_binding and not binding.extra.get("runner_binding"))
        )
        last_seen = binding.last_seen
        extra = dict(binding.extra)
        extra.update(context.extra)
        if is_runner_binding or binding.extra.get("runner_binding"):
            extra["runner_binding"] = True
        if is_runner_binding and context.parent_id:
            changed = changed or extra.get("parent_id") != context.parent_id
            extra["parent_id"] = context.parent_id
        if changed:
            extra["wake_context"] = updated
        clear_gone = extra.get("wake") == "gone"
        if now - last_seen >= timedelta(seconds=60) or clear_gone:
            last_seen = now
            if clear_gone:
                extra["wake"] = "active"
                extra["wake_cleared_at"] = _stamp(now)
            changed = True
        if changed:
            self._bindings[binding.address] = replace(
                binding, last_seen=last_seen, extra=extra
            )
            self._write()
        return changed

    def _touch_binding(self, address: str, now: datetime) -> None:
        binding = self._bindings.get(address)
        if binding is None:
            return
        extra = dict(binding.extra)
        clear_gone = extra.get("wake") == "gone"
        if now - binding.last_seen < timedelta(seconds=60) and not clear_gone:
            return
        if clear_gone:
            extra["wake"] = "active"
            extra["wake_cleared_at"] = _stamp(now)
        self._bindings[address] = replace(binding, last_seen=now, extra=extra)
        self._write()

    def refresh_current(
        self, harness: str, session_id: str, context: ReaderContext, now: datetime
    ) -> bool:
        if not (context.paseo_id or context.agent_id):
            return False
        with self._lock:
            binding = next(
                (
                    b
                    for b in self._bindings.values()
                    if b.harness == harness and b.session_id == session_id
                ),
                None,
            )
            if binding is None or self._current_sessions.get(
                binding.address
            ) != _session_key(harness, session_id):
                return False
            self._refresh_binding(binding, harness, session_id, context, now)
            return True

    def resolve_reader(
        self,
        harness: str,
        session_id: str,
        marker: str | None,
        context: ReaderContext,
        now: datetime,
    ) -> str | None:
        if not harness or not session_id:
            return None
        key = _session_key(harness, session_id)
        with self._lock:
            binding = next(
                (
                    b
                    for b in self._bindings.values()
                    if self._current_sessions.get(b.address) == key
                ),
                None,
            )
            if binding:
                self._refresh_binding(binding, harness, session_id, context, now)
                current = self._bindings[binding.address]
                if now - current.last_seen >= timedelta(seconds=60):
                    self._bindings[binding.address] = replace(current, last_seen=now)
                    self._write()
                return binding.address
        if marker and self.redeem(marker, session_id, harness, context, now=now):
            return self._current_address(key)
        if not (context.env_address and _NAME.fullmatch(context.env_address)):
            return None
        with self._lock:
            if self._live(context.env_address, now):
                return None
            fresh = self._mint(
                context.env_address,
                timedelta(hours=24),
                1,
                False,
                now,
                "VARDE_ADDRESS",
            )
            if self.redeem(fresh, session_id, harness, context, now=now):
                return context.env_address
        return None

    def _current_address(self, key: str) -> str | None:
        with self._lock:
            return next(
                (a for a, k in self._current_sessions.items() if k == key), None
            )

    def unbind(self, selector: str, now: datetime) -> bool:
        with self._lock:
            binding = next(
                (
                    b
                    for address, b in self._bindings.items()
                    if selector
                    in {address, b.session_id, _session_key(b.harness, b.session_id)}
                    and self._current_sessions.get(address)
                    == _session_key(b.harness, b.session_id)
                ),
                None,
            )
            if binding is None:
                return False
            token = self._tokens.get(binding.token_id)
            if token:
                self._tokens[token.token_id] = replace(token, uses_left=0)
            self._bindings.pop(binding.address)
            self._current_sessions.pop(binding.address, None)
            self._current_tokens.pop(binding.address, None)
            self._event("unbind", now, binding.address)
            self._write()
            return True

    def list_bindings(self) -> tuple[AddressBinding, ...]:
        with self._lock:
            return tuple(
                copy.deepcopy(self._bindings[key]) for key in sorted(self._bindings)
            )

    def live_addresses(self, now: datetime) -> frozenset[str]:
        with self._lock:
            return frozenset(
                a
                for a, binding in self._bindings.items()
                if now - binding.last_seen < timedelta(minutes=30)
            )

    def current_binding(self, address: str) -> AddressBinding | None:
        with self._lock:
            return copy.deepcopy(self._bindings.get(address))

    def current_token(self, address: str) -> str | None:
        with self._lock:
            return self._current_tokens.get(address)

    def address_names(self) -> frozenset[str]:
        with self._lock:
            names = (
                {
                    token.address
                    for token in self._tokens.values()
                    if token.address != "mailman"
                }
                | set(self._bindings)
                | set(self._current_tokens)
            )
            names.discard("mailman")
            return frozenset(names)

    def token_issue_times(self) -> Mapping[str, tuple[datetime, ...]]:
        with self._lock:
            result: dict[str, list[datetime]] = {}
            for token in self._tokens.values():
                result.setdefault(token.address, []).append(token.issued_at)
            return {name: tuple(sorted(times)) for name, times in result.items()}

    def wake_of(self, address: str) -> Mapping[str, object] | None:
        with self._lock:
            binding = self._bindings.get(address)
            if binding is None:
                return None
            wake = binding.extra.get("wake_context")
            if not isinstance(wake, Mapping):
                return None
            result = {k: v for k, v in wake.items() if k != "paseo_agent_id"}
            result.setdefault("harness", binding.harness)
            result.setdefault("paseo_id", wake.get("paseo_agent_id", ""))
            return result

    def mark_wake_gone(self, address: str, now: datetime) -> None:
        with self._lock:
            binding = self._bindings.get(address)
            if binding is None:
                return
            self._bindings[address] = replace(
                binding,
                extra={**binding.extra, "wake": "gone", "wake_gone_at": _stamp(now)},
            )
            self._write()

    def clear_wake_gone(self, address: str, now: datetime) -> None:
        with self._lock:
            binding = self._bindings.get(address)
            if binding is None or binding.extra.get("wake") != "gone":
                return
            self._bindings[address] = replace(
                binding,
                last_seen=now,
                extra={
                    **binding.extra,
                    "wake": "active",
                    "wake_cleared_at": _stamp(now),
                },
            )
            self._write()

    def events(self) -> tuple[AddressEvent, ...]:
        with self._lock:
            return copy.deepcopy(tuple(self._events))

    def last_refusal(self, address: str) -> AddressEvent | None:
        with self._lock:
            return copy.deepcopy(
                next(
                    (
                        event
                        for event in reversed(self._events)
                        if event.event == "refuse" and event.address == address
                    ),
                    None,
                )
            )

    def slots(self) -> tuple[AddressSlot, ...]:
        with self._lock:
            return tuple(self._slots.values())

    def resolve_alias(self, name: str) -> str:
        with self._lock:
            return next(
                (
                    slot.slot
                    for slot in self._slots.values()
                    if name == slot.slot or name in slot.aliases
                ),
                name,
            )

    def reader_addresses(self, name: str) -> frozenset[str]:
        with self._lock:
            slot = self.resolve_alias(name)
            record = self._slots.get(slot)
            return frozenset({slot, *(record.aliases if record else ())})

    def add_alias(self, slot: str, alias: str | None = None) -> None:
        if not _SLOT.fullmatch(slot) or (
            alias is not None and not _SLOT.fullmatch(alias)
        ):
            raise ValueError("invalid slot or alias")
        with self._lock:
            old = self._slots.get(slot, AddressSlot(slot, (), slot))
            aliases = old.aliases + (
                (alias,) if alias and alias != slot and alias not in old.aliases else ()
            )
            self._slots[slot] = replace(old, aliases=aliases, current_address=slot)
            self._write()

    def remove_alias(self, alias: str) -> None:
        if not _SLOT.fullmatch(alias):
            raise ValueError("invalid plan alias")
        with self._lock:
            changed = False
            for slot, old in tuple(self._slots.items()):
                aliases = tuple(item for item in old.aliases if item != alias)
                if aliases != old.aliases:
                    self._slots[slot] = replace(old, aliases=aliases)
                    changed = True
            if changed:
                self._write()

    def relay_snapshot(self) -> RelaySnapshot:
        with self._lock:
            return RelaySnapshot(
                tuple(copy.deepcopy(self._relay_events)),
                tuple(
                    copy.deepcopy(self._actions[key])
                    for key in self._leases
                    if key in self._actions
                ),
                copy.deepcopy(
                    {key: tuple(rows) for key, rows in self._attempts.items()}
                ),
                dict(self._started),
                Retirement(
                    frozenset(self._retired_addresses), frozenset(self._retired_tokens)
                ),
                frozenset(),
                dict(self._cycles),
                self._current_mailman,
                dict(self._instances),
                copy.deepcopy(self._escalations),
            )

    def record_event(
        self, event: str, *, now: datetime, data: Mapping[str, object] | None = None
    ) -> None:
        with self._lock:
            row: Mapping[str, object] = {
                "event": event,
                "at": _stamp(now),
                **(data or {}),
            }
            if event in {"waiting", "returned"}:
                self._relay_events = [
                    old
                    for old in self._relay_events
                    if not (
                        old.get("token_id") == row.get("token_id")
                        and old.get("event") in {"waiting", "returned"}
                    )
                ]
            if event in {"slept", "send-liveness"}:
                cutoff = now - (
                    timedelta(days=1) if event == "slept" else timedelta(days=3)
                )
                self._relay_events = [
                    old
                    for old in self._relay_events
                    if old.get("event") != event
                    or datetime.fromisoformat(str(old["at"])) >= cutoff
                ]
            if event == "send-liveness":
                indices = [
                    i
                    for i, old in enumerate(self._relay_events)
                    if old.get("event") == event
                ]
                for index in reversed(indices[:-199]):
                    del self._relay_events[index]
            self._relay_events.append(row)
            if event == "slept":
                raw_gap = row.get("gap_seconds", 0)
                gap = (
                    max(0.0, float(raw_gap))
                    if isinstance(raw_gap, (int, float))
                    else 0.0
                )
                delta = timedelta(seconds=gap)
                for action_id, action in tuple(self._actions.items()):
                    if action_id in self._leases:
                        self._actions[action_id] = replace(
                            action, expires_at=action.expires_at + delta
                        )
            self._write(wake=True)

    def record_events(self, events: Iterable[Mapping[str, object]]) -> None:
        with self._lock:
            self._relay_events.extend(dict(row) for row in events)
            if events:
                self._write(wake=True)

    def record_send_liveness(
        self, message_id: str, recipient: str, now: datetime
    ) -> None:
        self.record_event(
            "send-liveness",
            now=now,
            data={"message_id": message_id, "recipient": recipient},
        )

    def lease_actions(
        self,
        candidates: Iterable[Mapping[str, object]],
        token_id: str,
        now: datetime,
        *,
        lease_for: timedelta = timedelta(minutes=5),
        harness: str = "unknown",
    ) -> tuple[RelayAction, ...]:
        with self._lock:
            self._leases = {
                key
                for key in self._leases
                if key in self._actions and self._actions[key].expires_at > now
            }
            busy = {
                mid for key in self._leases for mid in self._actions[key].message_ids
            }
            result: list[RelayAction] = []
            for candidate in candidates:
                raw_ids = candidate.get("message_ids", ())
                ids_in = raw_ids if isinstance(raw_ids, (list, tuple, set)) else ()
                ids = tuple(str(mid) for mid in ids_in if str(mid) not in busy)
                if not ids:
                    continue
                action_id = secrets.token_hex(8)
                address = str(candidate.get("to", candidate.get("address", "")))
                wake = candidate.get("wake")
                selected_harness = (
                    str(wake.get("harness") or harness)
                    if isinstance(wake, Mapping)
                    else harness
                )
                payload = {
                    **candidate,
                    "address": address,
                    "to": address,
                    "message_ids": ids,
                    "harness": selected_harness,
                }
                prompt = payload.get("prompt")
                if isinstance(prompt, str):
                    payload["prompt"] = prompt.replace(
                        "[varde-delivery: pending ", f"[varde-delivery: {action_id} ", 1
                    )
                action = RelayAction(
                    action_id,
                    address,
                    ids,
                    token_id,
                    "leased",
                    now,
                    now + lease_for,
                    payload,
                )
                self._actions[action_id] = action
                self._leases.add(action_id)
                busy.update(ids)
                result.append(action)
            if result:
                self._write(wake=True)
            return tuple(result)

    def begin_confirm(self, action_id: str, result: str, now: datetime) -> ConfirmStart:
        if result not in {"pushed", "skipped-busy", "failed", "target-gone"}:
            raise ValueError("invalid confirmation result")
        with self._lock:
            action = self._actions.get(action_id)
            if action is None:
                self.record_event(
                    "unknown-confirm",
                    now=now,
                    data={"action_id": action_id, "result": result},
                )
                return ConfirmStart(ConfirmStatus.UNKNOWN)
            if action.status == "confirming":
                return ConfirmStart(
                    ConfirmStatus.RESUME,
                    action,
                    str(action.payload.get("result", result)),
                )
            if action.status != "leased":
                return ConfirmStart(ConfirmStatus.DUPLICATE, action, result)
            updated = replace(
                action,
                status="confirming",
                payload={**action.payload, "result": result},
            )
            self._actions[action_id] = updated
            self._leases.add(action_id)
            self._write(wake=True)
            return ConfirmStart(ConfirmStatus.BEGUN, updated, result)

    def finish_confirm(
        self,
        action_id: str,
        result: str,
        now: datetime,
        accepted_ids: Iterable[str],
        delivered: Iterable[tuple[str, str]],
    ) -> None:
        with self._lock:
            action = self._actions[action_id]
            accepted = set(accepted_ids)
            delivered_set = set(delivered)
            self._actions[action_id] = replace(
                action,
                status="confirmed",
                payload={
                    **action.payload,
                    "result": result,
                    "confirmed_at": _stamp(now),
                },
            )
            self._leases.discard(action_id)
            for mid in accepted:
                if result not in {"skipped-busy", "failed", "target-gone"}:
                    continue
                rows = self._attempts.setdefault(mid, [])
                if not any(row.get("action_id") == action_id for row in rows):
                    rows.append(
                        {"result": result, "at": _stamp(now), "action_id": action_id}
                    )
            for other_id, other in tuple(self._actions.items()):
                if other_id == action_id or other_id not in self._leases:
                    continue
                remaining = tuple(
                    mid
                    for mid in other.message_ids
                    if mid not in accepted and (mid, other.address) not in delivered_set
                )
                if remaining != other.message_ids:
                    self._actions[other_id] = replace(
                        other,
                        message_ids=remaining,
                        status="superseded" if not remaining else other.status,
                    )
                    if not remaining:
                        self._leases.discard(other_id)
            self._write(wake=True)

    def renew(
        self,
        action_id: str,
        now: datetime,
        *,
        lease_for: timedelta = timedelta(minutes=5),
    ) -> bool:
        with self._lock:
            action = self._actions.get(action_id)
            if (
                action is None
                or action.status != "leased"
                or action_id not in self._leases
            ):
                return False
            self._actions[action_id] = replace(action, expires_at=now + lease_for)
            self._write(wake=True)
            return True

    def end(self, token_id: str, now: datetime, *, instance_id: str) -> None:
        self.heartbeat(token_id, "ended", now, instance_id=instance_id)

    def heartbeat(
        self,
        token_id: str,
        status: str,
        now: datetime,
        *,
        instance_id: str,
        expect_return_by: datetime | None = None,
    ) -> None:
        with self._lock:
            if status != "ended" or not self._current_mailman:
                self._current_mailman = token_id
            previous = next(
                (
                    row
                    for row in reversed(self._relay_events)
                    if row.get("token_id") == token_id
                ),
                None,
            )
            old_instance = self._instances.get(token_id)
            if status == "waiting" and (
                old_instance != instance_id
                or previous is None
                or previous.get("event") in {"ended", "returned"}
            ):
                self._started[token_id] = now
            else:
                self._started.setdefault(token_id, now)
            self._instances[token_id] = instance_id
            row = {
                "event": status,
                "at": _stamp(now),
                "token_id": token_id,
                "expect_return_by": _stamp(expect_return_by)
                if expect_return_by
                else "",
            }
            if status in {"waiting", "returned"}:
                self._relay_events = [
                    old
                    for old in self._relay_events
                    if not (
                        old.get("token_id") == token_id
                        and old.get("event") in {"waiting", "returned"}
                    )
                ]
            self._relay_events.append(row)
            self._write(wake=True)

    def heartbeat_if_waiting(
        self,
        token_id: str,
        now: datetime,
        *,
        instance_id: str,
        expect_return_by: datetime | None = None,
    ) -> bool:
        with self._lock:
            latest = next(
                (
                    row
                    for row in reversed(self._relay_events)
                    if row.get("token_id") == token_id
                ),
                None,
            )
            if (
                self._current_mailman != token_id
                or self._instances.get(token_id) != instance_id
                or latest is None
                or latest.get("event") != "waiting"
            ):
                return False
            self.heartbeat(
                token_id,
                "waiting",
                now,
                instance_id=instance_id,
                expect_return_by=expect_return_by,
            )
            return True

    def return_mailman(
        self,
        token_id: str,
        now: datetime,
        expect_return_by: datetime,
        *,
        instance_id: str,
        completed: bool,
        reached_deadline: bool,
    ) -> bool:
        with self._lock:
            if reached_deadline:
                self._cycles[token_id] = self._cycles.get(token_id, 0) + 1
            self._instances[token_id] = instance_id
            self._relay_events = [
                row
                for row in self._relay_events
                if not (
                    row.get("token_id") == token_id
                    and row.get("event") in {"waiting", "returned"}
                )
            ]
            self._relay_events.append(
                {
                    "event": "returned",
                    "token_id": token_id,
                    "at": _stamp(now),
                    "expect_return_by": _stamp(expect_return_by),
                    "completed": completed,
                }
            )
            self._write(wake=True)
            return completed

    def mailman_alive(self, token_id: str, now: datetime) -> bool:
        with self._lock:
            return is_mailman_alive(token_id, now, self._relay_events)

    def action(self, action_id: str) -> RelayAction | None:
        with self._lock:
            return copy.deepcopy(self._actions.get(action_id))

    def superseded(self, token_id: str) -> bool:
        with self._lock:
            return self._current_tokens.get("mailman") != token_id

    def reserve_escalation(self, key: str, outcome: str, now: datetime) -> bool:
        with self._lock:
            if key in self._escalations:
                return False
            self._escalations[key] = {
                "status": "reserved",
                "outcome": outcome,
                "at": _stamp(now),
            }
            self._write(wake=True)
            return True

    def reserve_escalations(
        self, keys: Iterable[str], outcome: str, now: datetime
    ) -> set[str]:
        with self._lock:
            reserved = set(keys) - self._escalations.keys()
            if not reserved:
                return set()
            at = _stamp(now)
            self._escalations.update(
                {
                    key: {"status": "reserved", "outcome": outcome, "at": at}
                    for key in reserved
                }
            )
            self._write(wake=True)
            return reserved

    def reserve_suspect(self, key: str, now: datetime) -> bool:
        with self._lock:
            if key in self._suspects:
                return False
            self._suspects.add(key)
            self._write(wake=True)
            return True

    def retire(
        self, addresses: Iterable[str], tokens: Iterable[str], now: datetime
    ) -> None:
        with self._lock:
            address_rows, token_rows = set(addresses), set(tokens)
            self._retired_addresses.update(address_rows)
            self._retired_tokens.update(token_rows)
            stamp = _stamp(now)
            self._retired_at.update(dict.fromkeys(address_rows, stamp))
            self._retired_at.update({f"mailman:{token}": stamp for token in token_rows})
            self._write(wake=True)

    def unretire(self, addresses: Iterable[str]) -> None:
        with self._lock:
            changed = False
            for address in set(addresses):
                changed = self._retired_at.pop(address, None) is not None or changed
                changed = address in self._retired_addresses or changed
                self._retired_addresses.discard(address)
            if changed:
                self._write(wake=True)

    def retired(self) -> Retirement:
        with self._lock:
            return Retirement(
                frozenset(self._retired_addresses), frozenset(self._retired_tokens)
            )

    def retired_records(self) -> Mapping[str, str]:
        with self._lock:
            return dict(self._retired_at)

    def touch_wake(self) -> None:
        with self._lock:
            self._write(wake=True)

    def wake_token(self) -> Version:
        with self._lock:
            return Version(self._wake_revision)

    def version(self) -> Version:
        with self._lock:
            return Version(self._revision)

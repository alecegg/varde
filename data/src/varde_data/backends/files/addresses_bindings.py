"""Files adapter for address bindings, tokens, events, slots, and wake state."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from varde_data.backends.files.addresses_relay import FilesRelay
from varde_data.backends.memory.addresses import (
    _MARKER,
    _NAME,
    MemoryAddresses,
    _Token,
)
from varde_data.locking import atomic_write, file_lock, read_complete_lines
from varde_data.records.addresses import AddressBinding, AddressEvent, AddressSlot
from varde_data.version import Version, files_version

_BINDING_READS = {
    "marker_error",
    "list_bindings",
    "live_addresses",
    "current_binding",
    "current_token",
    "address_names",
    "token_issue_times",
    "wake_of",
    "events",
    "last_refusal",
    "slots",
    "resolve_alias",
    "reader_addresses",
    "version",
    "wake_token",
}
_BINDING_WRITES = {
    "issue",
    "redeem",
    "refresh_current",
    "resolve_reader",
    "unbind",
    "mark_wake_gone",
    "clear_wake_gone",
}
_SLOT_WRITES = {"add_alias", "remove_alias"}
_WRAPPED = _BINDING_READS | _BINDING_WRITES | _SLOT_WRITES


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _encoded(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return value if isinstance(value, dict) else None


class FilesAddresses(FilesRelay, MemoryAddresses):
    """Use the contract's in-memory semantics over the established file format."""

    def __init__(self, working: Path) -> None:
        self.working = working
        self.inbox = working / ".cache" / "inbox"
        self.address_root = self.inbox / "addresses"
        self.binding_root = self.inbox / "bindings"
        self.slot_root = self.inbox / "slots"
        self.event_path = self.inbox / "events.jsonl"

    def __getattribute__(self, name: str) -> object:
        if name in _WRAPPED:
            return partial(self._invoke, name)
        return super().__getattribute__(name)

    def _invoke(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "version":
            return self._version()
        if name == "wake_token":
            return files_version((self.inbox / "relay" / "relay.wake",))
        slots_only = name in {"slots", "resolve_alias", "reader_addresses"}
        lock_paths = self._locks(name, args, kwargs)
        if lock_paths:
            with self._acquire(lock_paths):
                return self._invoke_loaded(name, args, kwargs, slots_only)
        return self._invoke_loaded(name, args, kwargs, slots_only)

    def _invoke_loaded(
        self,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        slots_only: bool,
    ) -> Any:
        state = MemoryAddresses()
        self._load(state, slots_only=slots_only)
        if name == "current_token":
            address = str(args[0] if args else kwargs.get("address", ""))
            current = state.current_token(address)
            if current is not None:
                return current
            # The old mailman pointer predates binding records and contains
            # only {"token_id": ...}. Preserve its read semantics on upgrade.
            pointer = _read_json(self.address_root / address / "current")
            token_id = pointer.get("token_id") if pointer else None
            return token_id if isinstance(token_id, str) else None
        if name == "superseded":
            token_id = str(args[0] if args else kwargs.get("token_id", ""))
            current = state.current_token("mailman")
            if current is None:
                pointer = _read_json(self.address_root / "mailman" / "current")
                value = pointer.get("token_id") if pointer else None
                current = value if isinstance(value, str) else None
            return current != token_id
        if name == "address_names":
            names = set(state.address_names())
            if self.address_root.is_dir():
                names.update(
                    path.name
                    for path in self.address_root.iterdir()
                    if path.is_dir() and path.name != "mailman"
                )
            names.discard("mailman")
            return frozenset(names)
        before = self._state_copy(state)
        self._seed_marker(state, name, args, kwargs)
        try:
            result = getattr(state, name)(*args, **kwargs)
        finally:
            self._persist(name, state, before)
        return result

    @staticmethod
    def _state_copy(state: MemoryAddresses) -> dict[str, Any]:
        return {
            "bindings": copy.deepcopy(state._bindings),
            "sessions": dict(state._current_sessions),
            "current_tokens": dict(state._current_tokens),
            "tokens": dict(state._tokens),
            "slots": copy.deepcopy(state._slots),
            "event_count": len(state._events),
        }

    def _seed_marker(
        self,
        state: MemoryAddresses,
        name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        if name in {"redeem", "marker_error"}:
            marker = str(args[0] if args else kwargs.get("marker", ""))
        elif name == "resolve_reader":
            marker = str(args[2] if len(args) > 2 else kwargs.get("marker") or "")
        else:
            return
        match = _MARKER.fullmatch(marker)
        if not match:
            return
        address, secret = match.groups()
        digest = hashlib.sha256(secret.encode()).hexdigest()
        token = next(
            (
                item
                for item in state._tokens.values()
                if item.address == address and item.digest == digest
            ),
            None,
        )
        if token is not None:
            state._markers[secret] = token.token_id

    def _acquire(self, paths: tuple[Path, ...]) -> Any:
        from contextlib import ExitStack

        stack = ExitStack()
        for path in paths:
            stack.enter_context(file_lock(path, timeout=30))
            os.chmod(path, 0o644)
        return stack

    def _locks(
        self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> tuple[Path, ...]:
        if name in _SLOT_WRITES:
            return (self.slot_root / ".lock",)
        if name not in _BINDING_WRITES:
            return ()
        address = self._address_for(name, args, kwargs)
        if not address:
            return ()
        return (self.address_root / address / ".lock",)

    def _address_for(
        self, name: str, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> str | None:
        if name in {"issue", "mark_wake_gone", "clear_wake_gone"}:
            address = str(args[0] if args else kwargs.get("address", ""))
            return address if _NAME.fullmatch(address) else None
        if name == "redeem":
            marker = str(args[0] if args else kwargs.get("marker", ""))
            match = _MARKER.fullmatch(marker)
            return match.group(1) if match else None
        if name == "resolve_reader":
            harness = str(args[0] if args else kwargs.get("harness", ""))
            session = str(args[1] if len(args) > 1 else kwargs.get("session_id", ""))
            binding = self._find_binding(harness, session)
            if binding:
                return binding[0]
            context = args[3] if len(args) > 3 else kwargs.get("context")
            env_address = getattr(context, "env_address", None)
            if isinstance(env_address, str) and _NAME.fullmatch(env_address):
                return env_address
            marker = args[2] if len(args) > 2 else kwargs.get("marker")
            match = _MARKER.fullmatch(marker or "")
            return match.group(1) if match else None
        selector = str(args[0] if args else kwargs.get("selector", ""))
        if name == "refresh_current":
            harness = str(args[0] if args else kwargs.get("harness", ""))
            session = str(args[1] if len(args) > 1 else kwargs.get("session_id", ""))
            binding = self._find_binding(harness, session)
            return binding[0] if binding else None
        for path in self.binding_root.glob("*.json"):
            record = _read_json(path)
            if record and selector in {
                path.stem,
                record.get("session_id"),
                record.get("address"),
            }:
                address = record.get("address")
                if isinstance(address, str) and _NAME.fullmatch(address):
                    return address
        return selector if _NAME.fullmatch(selector) else None

    def _find_binding(
        self, harness: str, session: str
    ) -> tuple[str, dict[str, Any]] | None:
        key = f"{harness}-{hashlib.sha256(session.encode()).hexdigest()}"
        record = _read_json(self.binding_root / f"{key}.json")
        if record is None:
            return None
        address = record.get("address")
        return (address, record) if isinstance(address, str) else None

    def _load(self, state: MemoryAddresses, *, slots_only: bool = False) -> None:
        if not slots_only:
            for address_dir in (
                self.address_root.iterdir() if self.address_root.exists() else ()
            ):
                if not address_dir.is_dir():
                    continue
                current = _read_json(address_dir / "current")
                if current:
                    key, token_id = current.get("session_key"), current.get("token_id")
                    if isinstance(key, str) and isinstance(token_id, str):
                        record = _read_json(self.binding_root / f"{key}.json")
                        if record:
                            binding = self._binding_record(record)
                            if binding:
                                state._bindings[address_dir.name] = binding
                                state._current_sessions[address_dir.name] = key
                                state._current_tokens[address_dir.name] = token_id
                for token_path in (address_dir / "tokens").glob("*.json"):
                    token = _read_json(token_path)
                    if not token:
                        continue
                    issued = _time(token.get("issued_at"))
                    expires = _time(token.get("expires_at"))
                    if not issued or not expires:
                        continue
                    token_id = str(token.get("token_id", token_path.stem))
                    try:
                        uses_left = int(token.get("uses_left", 0))
                    except TypeError, ValueError:
                        uses_left = 0
                    state._tokens[token_id] = _Token(
                        token_id,
                        str(token.get("name", address_dir.name)),
                        str(token.get("sha256", "")),
                        issued,
                        expires,
                        uses_left,
                        token.get("supersede") is True,
                        str(token.get("issuer", "unknown")),
                    )

            for line in read_complete_lines(self.event_path):
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                at = _time(row.get("at"))
                event = row.get("event")
                if not at or not isinstance(event, str):
                    continue
                known = {
                    "event",
                    "at",
                    "address",
                    "session_id",
                    "token_id",
                    "session_key",
                }
                state._events.append(
                    AddressEvent(
                        event,
                        at,
                        row.get("address")
                        if isinstance(row.get("address"), str)
                        else None,
                        row.get("session_id")
                        if isinstance(row.get("session_id"), str)
                        else None,
                        row.get("token_id")
                        if isinstance(row.get("token_id"), str)
                        else None,
                        row.get("session_key")
                        if isinstance(row.get("session_key"), str)
                        else None,
                        {key: value for key, value in row.items() if key not in known},
                    )
                )

        for path in self.slot_root.glob("*.json"):
            record = _read_json(path)
            if not record:
                continue
            slot, aliases = record.get("slot"), record.get("aliases")
            if isinstance(slot, str) and isinstance(aliases, list):
                state._slots[slot] = AddressSlot(
                    slot,
                    tuple(alias for alias in aliases if isinstance(alias, str)),
                    record.get("current_address")
                    if isinstance(record.get("current_address"), str)
                    else None,
                )

    def _binding_record(self, record: dict[str, Any]) -> AddressBinding | None:
        address = record.get("address")
        bound_at, last_seen = (
            _time(record.get("bound_at")),
            _time(record.get("last_seen")),
        )
        if not isinstance(address, str):
            return None
        # Older workflow bindings may omit one or both timestamps.
        bound_at = bound_at or last_seen or datetime(1970, 1, 1, tzinfo=UTC)
        last_seen = last_seen or bound_at
        standard = {
            "address",
            "harness",
            "session_id",
            "bound_at",
            "last_seen",
            "token_id",
        }
        extra = {key: value for key, value in record.items() if key not in standard}
        return AddressBinding(
            address,
            str(record.get("session_id", "")),
            str(record.get("harness", "")),
            bound_at,
            last_seen,
            str(record.get("token_id", "")),
            extra,
        )

    def _persist(
        self, name: str, state: MemoryAddresses, before: dict[str, Any]
    ) -> None:
        if name in _SLOT_WRITES:
            self._persist_slots(state, before["slots"])
            return
        if name not in _BINDING_WRITES:
            return
        self._persist_bindings(state, before)
        if len(state._events) > before["event_count"]:
            with file_lock(self.inbox / ".events.lock", timeout=30):
                self._persist_events(state, before["event_count"])

    def _persist_bindings(self, state: MemoryAddresses, before: dict[str, Any]) -> None:
        changed_addresses = {
            address
            for address in (
                set(before["bindings"])
                | set(state._bindings)
                | set(before["sessions"])
                | set(state._current_sessions)
                | set(before["current_tokens"])
                | set(state._current_tokens)
            )
            if (
                before["bindings"].get(address) != state._bindings.get(address)
                or before["sessions"].get(address)
                != state._current_sessions.get(address)
                or before["current_tokens"].get(address)
                != state._current_tokens.get(address)
            )
        }
        for address in changed_addresses:
            binding = state._bindings.get(address)
            key = state._current_sessions.get(address)
            if binding is not None and key is not None:
                record: dict[str, object] = {
                    "address": binding.address,
                    "harness": binding.harness,
                    "session_id": binding.session_id,
                    "bound_at": _timestamp(binding.bound_at),
                    "cwd": binding.extra.get("cwd", "."),
                    "token_id": binding.token_id,
                    "last_seen": _timestamp(binding.last_seen),
                }
                wake_context = binding.extra.get("wake_context")
                if wake_context is not None:
                    record["wake_context"] = wake_context
                reserved = {"cwd", "wake_context"}
                record.update(
                    {k: v for k, v in binding.extra.items() if k not in reserved}
                )
                self._write_if_changed(self.binding_root / f"{key}.json", record, 0o600)
                self._write_if_changed(
                    self.address_root / address / "current",
                    {"session_key": key, "token_id": binding.token_id},
                    0o600,
                )
            elif before["current_tokens"].get(address) is not None:
                (self.address_root / address / "current").unlink(missing_ok=True)

        changed_tokens = {
            token_id
            for token_id in set(before["tokens"]) | set(state._tokens)
            if before["tokens"].get(token_id) != state._tokens.get(token_id)
        }
        for token_id in changed_tokens:
            prior = before["tokens"].get(token_id)
            current = state._tokens.get(token_id)
            token = current or prior
            if token is None:
                continue
            path = self.address_root / token.address / "tokens" / f"{token_id}.json"
            if current is None:
                path.unlink(missing_ok=True)
                continue
            record: dict[str, object] = {
                "token_id": current.token_id,
                "name": current.address,
                "sha256": current.digest,
                "issued_at": _timestamp(current.issued_at),
                "expires_at": _timestamp(current.expires_at),
                "uses_left": current.uses_left,
                "supersede": current.supersede,
                "issuer": current.issuer,
            }
            self._write_if_changed(path, record, 0o600)

    def _persist_events(self, state: MemoryAddresses, event_count: int) -> None:
        rows = state._events[event_count:]
        if not rows:
            return
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        prefix = b""
        try:
            with self.event_path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                if stream.tell():
                    stream.seek(-1, os.SEEK_END)
                    if stream.read(1) != b"\n":
                        prefix = b"\n"
        except FileNotFoundError:
            pass
        payload = bytearray(prefix)
        for row in rows:
            record: dict[str, object] = {"event": row.event, "at": _timestamp(row.at)}
            if row.address is not None:
                record["address"] = row.address
            if row.event == "bind" and row.session_key is not None:
                record["session_key"] = row.session_key
            if row.event == "token-reuse" and row.token_id is not None:
                record["token_id"] = row.token_id
            record.update(row.details)
            payload.extend(_encoded(record) + b"\n")
        descriptor = os.open(
            self.event_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644
        )
        try:
            written = os.write(descriptor, payload)
            if written != len(payload):
                raise OSError("short write appending address events")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _persist_slots(
        self, state: MemoryAddresses, before: dict[str, AddressSlot]
    ) -> None:
        self.slot_root.mkdir(parents=True, exist_ok=True)
        for name in set(before) | set(state._slots):
            prior, slot = before.get(name), state._slots.get(name)
            if prior == slot:
                continue
            path = self.slot_root / f"{name}.json"
            if slot is None:
                path.unlink(missing_ok=True)
                continue
            record = _read_json(path) or {}
            record.update(
                slot=slot.slot,
                aliases=list(slot.aliases),
                current_address=slot.current_address or slot.slot,
            )
            payload = (json.dumps(record, sort_keys=True) + "\n").encode("utf-8")
            atomic_write(path, payload, mode=0o644)

    @staticmethod
    def _write_if_changed(path: Path, record: object, mode: int) -> None:
        payload = _encoded(record)
        if path.exists() and path.read_bytes() == payload:
            return
        atomic_write(path, payload, mode=mode)

    def _version(self) -> Version:
        relay_root = self.inbox / "relay"
        address_dirs = (
            tuple(
                path
                for path in self.address_root.iterdir()
                if path.is_dir()
                and ((path / "current").exists() or (path / "tokens").is_dir())
            )
            if self.address_root.is_dir()
            else ()
        )
        sources = (
            self.event_path,
            relay_root / "relay.wake",
            relay_root / "state.json",
            relay_root / "actions",
            self.binding_root,
            *address_dirs,
            *(path / "tokens" for path in address_dirs if (path / "tokens").is_dir()),
            self.slot_root,
        )
        existing = tuple(path for path in sources if path.exists())
        return files_version(existing) if existing else Version(0)

    def wake_token(self) -> Version:
        path = self.inbox / "relay" / "relay.wake"
        return files_version((path,))

    def touch_wake(self) -> None:
        path = self.inbox / "relay" / "relay.wake"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

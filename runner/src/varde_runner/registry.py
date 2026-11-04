"""Durable address-to-session registry for supervised sessions."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_MARKER = re.compile(
    r"\[varde-address: ([A-Za-z0-9._-]{1,64}) (vt1\.[A-Z2-7]{26})\]\Z",
    re.ASCII,
)


@dataclass(frozen=True, slots=True)
class SessionBinding:
    address: str
    harness: str
    adapter: str
    session_id: str
    role: str
    plan_id: str | None = None


class SessionRegistry:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._bindings: dict[str, SessionBinding] = {}
        self._expected_markers: dict[str, dict[str, str | int]] = {}
        self._load()

    def expect_marker(self, marker: str) -> None:
        parsed = _parse_marker(marker)
        if parsed is None:
            raise ValueError("invalid Varde address marker")
        address, token = parsed
        with self._locked():
            self._expected_markers[address] = {
                "sha256": _token_digest(token),
                "expires_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
                "uses_left": 1,
            }
            self._save()

    def register(self, binding: SessionBinding) -> None:
        with self._locked():
            self._store(binding)
            self._save()

    def bind_first_prompt(self, prompt: str, binding: SessionBinding) -> bool:
        parsed = next(
            (
                marker
                for line in prompt.split("\n")[:5]
                if (marker := _parse_marker(line.removesuffix("\r"))) is not None
            ),
            None,
        )
        if parsed is None:
            return False
        address, token = parsed
        digest = _token_digest(token)
        with self._locked():
            expected = self._expected_markers.get(address)
            if expected is None or not hmac.compare_digest(
                str(expected["sha256"]), digest
            ):
                return False
            if datetime.now(UTC) >= datetime.fromisoformat(str(expected["expires_at"])):
                del self._expected_markers[address]
                return False
            if int(expected["uses_left"]) < 1:
                return False
            bound = SessionBinding(
                address,
                binding.harness,
                binding.adapter,
                binding.session_id,
                binding.role,
                binding.plan_id,
            )
            self._store(bound)
            del self._expected_markers[address]
            self._save()
        return True

    def resolve(self, address: str) -> SessionBinding | None:
        with self._locked():
            return self._bindings.get(address)

    def bindings_by_session_id(self) -> dict[str, SessionBinding]:
        """Return a snapshot of registered bindings keyed by session id."""
        with self._locked():
            return {binding.session_id: binding for binding in self._bindings.values()}

    def _store(self, binding: SessionBinding) -> None:
        self._bindings[binding.address] = binding
        if binding.plan_id:
            self._bindings[binding.plan_id] = binding

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                self._load()
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def _load(self) -> None:
        if not self.path.exists():
            self._bindings = {}
            self._expected_markers = {}
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if "bindings" not in data:
            self._bindings = {
                address: _binding_from_row(row) for address, row in data.items()
            }
            self._expected_markers = {}
            return
        self._bindings = {
            address: _binding_from_row(row)
            for address, row in data.get("bindings", {}).items()
        }
        self._expected_markers = {
            address: (
                record
                if isinstance(record, dict)
                else {
                    "sha256": record,
                    "expires_at": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
                    "uses_left": 1,
                }
            )
            for address, record in data.get("expected_markers", {}).items()
        }

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + f".{os.getpid()}.tmp")
        temp.write_text(
            json.dumps(
                {
                    "bindings": {
                        key: asdict(value) for key, value in self._bindings.items()
                    },
                    "expected_markers": self._expected_markers,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temp, self.path)


def _parse_marker(line: str) -> tuple[str, str] | None:
    match = _MARKER.fullmatch(line)
    if match is None:
        return None
    address, token = match.groups()
    return address, token


def _binding_from_row(row: dict[str, Any]) -> SessionBinding:
    values = dict(row)
    if "adapter" not in values:
        values["adapter"] = values.pop("provider")
    return SessionBinding(**values)


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()

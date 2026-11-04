"""Client role bindings and in-memory interactive writer leases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic

SYSTEM_CLIENT_IDS = frozenset(
    {"system:relay", "system:delivery", "system:dashboard", "system:governor"}
)


class ClientRole(StrEnum):
    WRITER = "writer"
    OBSERVER = "observer"


class ObserverReadOnly(PermissionError):
    """Raised when an observer client attempts a write."""


class UnknownClient(PermissionError):
    """Raised when a write names a client that is not attached."""


class WriterBusy(RuntimeError):
    def __init__(self, holder: str) -> None:
        self.holder = holder
        super().__init__(f"writer lease is held by {holder}")


class ClientRegistry:
    def __init__(self) -> None:
        self._roles: dict[tuple[str, str], tuple[ClientRole, int]] = {}

    def attach(self, session_id: str, client_id: str, role: ClientRole | str) -> None:
        if not client_id or client_id.startswith("system:"):
            raise ValueError("system client ids cannot attach")
        role = ClientRole(role)
        key = (session_id, client_id)
        current = self._roles.get(key)
        if current is not None and current[0] != role:
            raise ValueError("client is already attached with another role")
        self._roles[key] = (role, current[1] + 1 if current else 1)

    def detach(self, session_id: str, client_id: str) -> bool:
        key = (session_id, client_id)
        current = self._roles.get(key)
        if current is None:
            return False
        if current[1] == 1:
            self._roles.pop(key)
            return True
        self._roles[key] = (current[0], current[1] - 1)
        return False

    def role(self, session_id: str, client_id: str) -> ClientRole | None:
        current = self._roles.get((session_id, client_id))
        return current[0] if current is not None else None

    def has_clients(self, session_id: str) -> bool:
        return any(key[0] == session_id for key in self._roles)


@dataclass
class _Lease:
    client_id: str
    expires_at: float


class WriterLeases:
    """Interactive ownership lasts across successful writes and refreshes on each.

    A disconnected client releases its lease; otherwise idle writers expire lazily.
    The lease serializes write starts, not the duration of an in-flight call.
    """

    def __init__(
        self,
        timeout: float = 60.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.timeout = timeout
        self._clock = clock
        self._holders: dict[str, _Lease] = {}

    def acquire(self, session_id: str, client_id: str) -> None:
        now = self._clock()
        self._expire(session_id, now)
        current = self._holders.get(session_id)
        if current is not None and current.client_id != client_id:
            raise WriterBusy(current.client_id)
        self._holders[session_id] = _Lease(client_id, now + self.timeout)

    def release(self, session_id: str, client_id: str) -> None:
        current = self._holders.get(session_id)
        if current is not None and current.client_id == client_id:
            self._holders.pop(session_id, None)

    def preempt_bot(self, session_id: str, client_id: str) -> None:
        """A non-bot client takes the lease from a `bot:*` holder."""
        current = self._holders.get(session_id)
        if (
            current is not None
            and current.client_id.startswith("bot:")
            and not client_id.startswith("bot:")
        ):
            self._holders.pop(session_id, None)

    def clear(self, session_id: str) -> None:
        """Release any writer lease for a session that is being closed."""
        self._holders.pop(session_id, None)

    def holder(self, session_id: str) -> str | None:
        now = self._clock()
        self._expire(session_id, now)
        current = self._holders.get(session_id)
        return current.client_id if current is not None else None

    def _expire(self, session_id: str, now: float) -> None:
        current = self._holders.get(session_id)
        if current is not None and current.expires_at <= now:
            self._holders.pop(session_id, None)

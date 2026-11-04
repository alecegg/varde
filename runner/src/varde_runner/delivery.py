"""Idle-gated delivery with a shared claim log."""

from __future__ import annotations

import fcntl
import json
from collections.abc import Callable, Iterable
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from varde_runner.registry import SessionRegistry
from varde_runner.supervisor import SendOutcome


class DeliverySupervisor(Protocol):
    async def is_idle(self, session_id: str, harness: str | None = None) -> bool: ...
    async def send(
        self, session_id: str, prompt: str, harness: str | None = None
    ) -> SendOutcome: ...


class DeliveryLoop:
    def __init__(
        self,
        log_path: Path,
        registry: SessionRegistry,
        supervisor: DeliverySupervisor,
        messages: Callable[[], Iterable[dict[str, Any]]],
    ) -> None:
        self.log_path = log_path
        self.registry = registry
        self.supervisor = supervisor
        self.messages = messages

    async def deliver_once(self) -> int:
        delivered = 0
        for message in self.messages():
            message_id = str(message.get("id", ""))
            binding = self.registry.resolve(str(message.get("to", "")))
            if not message_id or binding is None:
                continue
            prompt = str(message.get("text") or message.get("body") or "")
            if not await self.supervisor.is_idle(binding.session_id, binding.harness):
                continue
            if not claim_message(self.log_path, message_id, "supervisor"):
                continue
            try:
                outcome = await self.supervisor.send(
                    binding.session_id, prompt, binding.harness
                )
            except Exception as exc:  # noqa: BLE001 - isolate failures per message
                release_claim(self.log_path, message_id, type(exc).__name__)
                continue
            if outcome == SendOutcome.QUEUED:
                record_pushed(self.log_path, message_id, binding.session_id)
                delivered += 1
                continue
            if outcome != SendOutcome.SENT:
                release_claim(self.log_path, message_id, str(outcome))
                continue
            record_pushed(self.log_path, message_id, binding.session_id)
            delivered += 1
        return delivered


def claim_message(log_path: Path, message_id: str, claimant: str) -> bool:
    """Claim one message atomically across supervisor and hook processes."""
    with _file_lock(log_path):
        if message_id in _states(log_path):
            return False
        _append(
            log_path,
            {
                "event": "claimed",
                "message_id": message_id,
                "claimant": claimant,
            },
        )
    return True


def release_claim(log_path: Path, message_id: str, error_type: str) -> None:
    with _file_lock(log_path):
        _append(
            log_path,
            {
                "event": "claim_failed",
                "message_id": message_id,
                "error_type": error_type,
            },
        )


def record_pushed(log_path: Path, message_id: str, session_id: str) -> None:
    with _file_lock(log_path):
        _append(
            log_path,
            {
                "event": "pushed",
                "message_id": message_id,
                "session_id": session_id,
                "at": datetime.now(UTC).isoformat(),
            },
        )


@contextmanager
def _file_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _states(path: Path) -> set[str]:
    state: dict[str, str] = {}
    if not path.exists():
        return set()
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        message_id = str(row["message_id"])
        if row["event"] == "claim_failed":
            state.pop(message_id, None)
        elif row["event"] in {"claimed", "pushed"}:
            state[message_id] = str(row["event"])
    return set(state)


def _append(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        handle.flush()

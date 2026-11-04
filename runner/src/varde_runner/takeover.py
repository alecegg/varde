"""Persisted instance takeover and ordered delivery of deferred sends."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from varde_data.errors import NotFound
from varde_data.repos.chat import ChatRepository

from varde_runner.supervisor import SendOutcome
from varde_runner.takeover_state import expired, should_queue


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class Takeover:
    def __init__(
        self,
        repository: ChatRepository,
        *,
        clock: Callable[[], datetime] = _now,
        retry_seconds: float = 0.1,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.retry_seconds = retry_seconds
        self._agent_locks: dict[str, asyncio.Lock] = {}
        self._drains: dict[str, asyncio.Task[None]] = {}

    def acquire(self, agent_id: str, holder: str) -> bool:
        key = _thread_key(agent_id)
        now = self.clock()
        try:
            current = self.repository.get_takeover(key)
        except NotFound:
            return False
        if current is not None and current.released_at is None:
            if expired(current.heartbeat_at, now):
                self.repository.release(key, current.holder_client, _stamp(now))
                self._event(
                    key, "takeover_expired", "Takeover released after heartbeat expired"
                )
            elif current.holder_client != holder:
                return False
        row = self.repository.acquire(key, holder, _stamp(now))
        if row is None:
            return False
        self._event(key, "takeover", "User took over this instance")
        return True

    def heartbeat(self, agent_id: str, holder: str) -> bool:
        key = _thread_key(agent_id)
        try:
            current = self.repository.get_takeover(key)
        except NotFound:
            return False
        now = self.clock()
        if (
            current is None
            or current.released_at is not None
            or current.holder_client != holder
        ):
            return False
        if expired(current.heartbeat_at, now):
            self.release_expired(key, current.holder_client, now)
            return False
        return self.repository.heartbeat(key, holder, _stamp(now))

    def release(
        self, agent_id: str, holder: str, supervisor: Any | None = None
    ) -> bool:
        key = _thread_key(agent_id)
        now = self.clock()
        if not self.repository.release(key, holder, _stamp(now)):
            return False
        self._event(key, "takeover_released", "User released this instance")
        self._schedule_drain(agent_id, supervisor)
        return True

    def release_for_lifecycle(
        self, agent_id: str, supervisor: Any | None = None
    ) -> None:
        key = _thread_key(agent_id)
        try:
            current = self.repository.get_takeover(key)
        except NotFound:
            return
        if current is None or current.released_at is not None:
            return
        now = self.clock()
        if self.repository.release(key, current.holder_client, _stamp(now)):
            self._event(
                key, "takeover_released", "Takeover released by instance lifecycle"
            )
            self._schedule_drain(agent_id, supervisor)

    def should_queue(
        self,
        agent_id: str,
        sender_class: str,
        text: str,
        *,
        request_id: str | None,
        supervisor: Any | None = None,
    ) -> bool:
        """Persist an intercepted send and return whether it was accepted."""
        if sender_class != "other":
            return False
        key = _thread_key(agent_id)
        now = self.clock()
        try:
            current = self.repository.get_takeover(key)
        except NotFound:
            return False
        held = current is not None and current.released_at is None
        lease_expired = bool(current and held and expired(current.heartbeat_at, now))
        if lease_expired and current is not None:
            self.release_expired(key, current.holder_client, now)
        has_earlier = self.repository.next_queued(key) is not None
        if (
            not should_queue(
                held=held, lease_expired=lease_expired, sender_class=sender_class
            )
            and not has_earlier
        ):
            return False
        item = self.repository.enqueue(
            key,
            sender_class,
            "prompt",
            text,
            _stamp(now),
            request_id=request_id,
        )
        queued = self.repository.queued_count(key)
        self._event(
            key,
            "takeover_queued",
            f"Queued {sender_class} message {item.id}; {queued} waiting",
        )
        if not held:
            self._schedule_drain(agent_id, supervisor)
        return True

    def release_expired(
        self, thread_key: str, holder: str, now: datetime | None = None
    ) -> None:
        timestamp = now or self.clock()
        if self.repository.release(thread_key, holder, _stamp(timestamp)):
            self._event(
                thread_key,
                "takeover_expired",
                "Takeover released after heartbeat expired",
            )

    async def start(self, supervisor: Any) -> None:
        """Recover active holds and deferred sends after the runner starts."""
        store = getattr(supervisor, "store", None)
        if store is None:
            return
        for session in store.sessions():
            agent_id = str(session.get("agent_id") or session.get("id") or "")
            if not agent_id:
                continue
            key = _thread_key(agent_id)
            try:
                current = self.repository.get_takeover(key)
            except NotFound:
                continue
            if current is not None and current.released_at is None:
                if expired(current.heartbeat_at, self.clock()):
                    self.release_expired(key, current.holder_client)
                else:
                    continue
            self._schedule_drain(agent_id, supervisor)

    def _schedule_drain(self, agent_id: str, supervisor: Any | None) -> None:
        task = self._drains.get(agent_id)
        if task is not None and not task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._drains[agent_id] = loop.create_task(self._drain(agent_id, supervisor))

    def drain(self, agent_id: str, supervisor: Any) -> None:
        self._schedule_drain(agent_id, supervisor)

    async def _drain(self, agent_id: str, supervisor: Any | None) -> None:
        key = _thread_key(agent_id)
        lock = self._agent_locks.setdefault(agent_id, asyncio.Lock())
        async with lock:
            while True:
                if self._held(key):
                    return
                item = self.repository.next_queued(key)
                if item is None:
                    return
                active_supervisor = supervisor
                if active_supervisor is None:
                    return
                session = active_supervisor.resolve_session(agent_id)
                if session is None or session.get("lifecycle") in {
                    "completed",
                    "archived",
                    "error",
                }:
                    if self.repository.drop(key, item.id, "agent_not_live"):
                        self._event(
                            key,
                            "takeover_dropped",
                            f"Dropped queued message {item.id}: agent is not live",
                        )
                    continue
                outcome = await active_supervisor.send(
                    agent_id,
                    item.text,
                    client_id="system:takeover-queue",
                    request_id=item.request_id,
                    takeover_holder=True,
                )
                if outcome == SendOutcome.SENT:
                    self.repository.mark_delivered(
                        key, item.id, "SENT", _stamp(self.clock())
                    )
                    await self._wait_for_next_idle(active_supervisor, agent_id)
                    continue
                if outcome in {SendOutcome.NOT_FOUND, SendOutcome.FAILED}:
                    if self.repository.drop(key, item.id, outcome.value):
                        self._event(
                            key,
                            "takeover_dropped",
                            f"Dropped queued message {item.id}: {outcome.value}",
                        )
                    continue
                await asyncio.sleep(self.retry_seconds)

    async def _wait_for_next_idle(self, supervisor: Any, agent_id: str) -> None:
        while True:
            status = await supervisor.target_idle_status(agent_id)
            value = status.get("status") if isinstance(status, dict) else status
            if value in {"closed", "not-found", "error"}:
                return
            idle = status == "idle" or (
                isinstance(status, dict) and status.get("status") == "idle"
            )
            if idle:
                return
            await asyncio.sleep(self.retry_seconds)

    def _held(self, key: str) -> bool:
        current = self.repository.get_takeover(key)
        if current is None or current.released_at is not None:
            return False
        if expired(current.heartbeat_at, self.clock()):
            self.release_expired(key, current.holder_client)
            return False
        return True

    def _event(self, key: str, kind: str, summary: str) -> None:
        self.repository.append_event(kind, summary, None, thread_key=key)


def _thread_key(agent_id: str) -> str:
    return f"instance:{agent_id}"

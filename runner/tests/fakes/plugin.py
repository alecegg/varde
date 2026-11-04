"""A small non-Paseo implementation of the runner plugin contract."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from varde_runner.config import Model
from varde_runner.events import RunnerEvent
from varde_runner.plugins import (
    RunnerCapabilities,
    SessionRef,
    SessionSettings,
    SessionSpec,
)
from varde_runner.protocol import ResumeSettings


class FakePlugin:
    def __init__(self, capabilities: RunnerCapabilities | None = None) -> None:
        self.capabilities = capabilities or RunnerCapabilities(
            resume=True, idle_status=True, respond=True, interrupt=True
        )
        self.sent: list[tuple[str, str]] = []
        self.responses: list[tuple[str, str]] = []
        self.started: list[SessionSpec] = []
        self.stopped: list[str] = []
        self.resumed: list[str] = []
        self.resumed_settings: list[ResumeSettings | None] = []
        self.interrupted: list[str] = []
        self.status: dict[str, str] = {}
        self._events: dict[str, asyncio.Queue[RunnerEvent | None]] = {}
        self._send_started: asyncio.Event | None = None
        self._release_send: asyncio.Event | None = None
        self.interrupt_sets_idle = True

    def session_settings(self, model: Model) -> SessionSettings:
        return SessionSettings(model.model, model.reasoning_effort, model.mode)

    def is_provider_limit_error(self, exc: BaseException) -> bool:
        return False

    async def start(self, spec: SessionSpec) -> SessionRef:
        self.started.append(spec)
        ref = SessionRef(spec.provider, f"remote-{len(self.started)}")
        self.status[ref.session_id] = "idle"
        self._events[ref.session_id] = asyncio.Queue()
        return ref

    async def send(self, ref: SessionRef, prompt: str) -> None:
        if self._send_started is not None:
            self._send_started.set()
        if self._release_send is not None:
            await self._release_send.wait()
        self.sent.append((ref.session_id, prompt))
        self.status[ref.session_id] = "running"

    async def idle_status(self, ref: SessionRef) -> str:
        return self.status.get(ref.session_id, "unknown")

    async def events(self, ref: SessionRef) -> AsyncGenerator[RunnerEvent]:
        queue = self._events.setdefault(ref.session_id, asyncio.Queue())
        while True:
            event = await queue.get()
            if event is None:
                return
            yield event

    async def emit(self, ref: SessionRef, event: RunnerEvent) -> None:
        if event.kind == "status":
            self.status[ref.session_id] = str(event.payload.get("status", "unknown"))
        await self._events.setdefault(ref.session_id, asyncio.Queue()).put(event)

    async def respond_permission(
        self, ref: SessionRef, request_id: str, decision: str
    ) -> None:
        self.responses.append((request_id, decision))

    async def stop(self, ref: SessionRef) -> None:
        self.stopped.append(ref.session_id)
        await self._events.setdefault(ref.session_id, asyncio.Queue()).put(None)

    def validate_resume_mode(self, mode: str) -> None:
        if mode not in {"auto", "full-access", "read-only"}:
            raise ValueError(f"unsupported runner mode: {mode}")

    async def resume(
        self, ref: SessionRef, settings: ResumeSettings | None = None
    ) -> SessionRef:
        if not self.capabilities.resume:
            raise RuntimeError("resume unsupported")
        self.resumed.append(ref.session_id)
        self.resumed_settings.append(settings)
        self.status.setdefault(ref.session_id, "idle")
        self._events.setdefault(ref.session_id, asyncio.Queue())
        return ref

    async def interrupt(self, ref: SessionRef) -> None:
        self.interrupted.append(ref.session_id)
        if self.interrupt_sets_idle:
            self.status[ref.session_id] = "idle"

    async def close(self) -> None:
        return None

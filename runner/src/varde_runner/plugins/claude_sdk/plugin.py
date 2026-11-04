"""Claude Agent SDK adapter hosted by the shared Node host."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from uuid import uuid4

from varde_runner.config import Model, adapter_state_root, claude_sdk_settings
from varde_runner.events import RunnerEvent
from varde_runner.node_host.host import NodeHost
from varde_runner.node_host.policy import RestartPolicy
from varde_runner.node_host_config import node_host_engine_path, node_host_settings
from varde_runner.plugins import (
    RunnerCapabilities,
    SessionRef,
    SessionSettings,
    SessionSpec,
    child_environment,
    process_state,
)
from varde_runner.protocol import ResumeSettings

logger = logging.getLogger(__name__)
REMOVED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
)
EVENT_KINDS = {
    "text",
    "tool_intent",
    "tool_result",
    "permission_requested",
    "permission_resolved",
    "status",
    "usage",
    "session_end",
    "error",
}
SUPPORTED_MODES = {"read-only", "workspace-write", "auto", "full-access"}


def child_env(spec: SessionSpec) -> dict[str, str]:
    env = host_env()
    env.update(
        VARDE_AGENT_ID=spec.agent_id or spec.workspace_id, VARDE_HARNESS="claude-sdk"
    )
    return env


def host_env() -> dict[str, str]:
    return {
        key: value
        for key, value in child_environment().items()
        if key not in REMOVED_ENV_VARS
    }


class ClaudeSdkPlugin:
    config_table = "claude_sdk"
    capabilities = RunnerCapabilities(
        resume=True,
        permission_commands=True,
        usage=True,
        idle_status=True,
        persistent_process=True,
        interrupt=True,
        respond=True,
    )

    def __init__(
        self,
        *,
        state_dir: str | Path | None = None,
        settings_text: str | None = None,
        host: NodeHost | None = None,
    ) -> None:
        self.state_dir = (
            Path(state_dir) if state_dir else adapter_state_root() / "claude-sdk"
        )
        self.settings_text = settings_text
        self.host = host
        self._specs: dict[str, SessionSpec] = {}
        self._handles: dict[str, str] = {}
        self._queues: dict[str, asyncio.Queue[RunnerEvent | None]] = {}
        self._subscriptions: dict[str, Any] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stopped: set[str] = set()
        self._interrupted: set[str] = set()
        self._pending: dict[str, set[str]] = {}
        self._resuming: asyncio.Lock = asyncio.Lock()

    def session_settings(self, model: Model) -> SessionSettings:
        return SessionSettings(model.model, model.reasoning_effort, model.mode)

    def _host(self) -> NodeHost:
        if self.host is None:
            from varde_runner.config import config_path, default_toml

            text = self.settings_text
            if text is None:
                path = config_path()
                text = (
                    path.read_text(encoding="utf-8")
                    if path.exists()
                    else default_toml()
                )
            settings = node_host_settings(text)
            env = host_env()
            engine_path = node_host_engine_path("claude-sdk")
            host_script = engine_path.parents[2] / "host.mjs"
            self.host = NodeHost(
                [settings.node, str(host_script)],
                engine_path,
                env,
                RestartPolicy(
                    max_restarts=settings.restart_max,
                    window_s=settings.restart_window_s,
                ),
                state_path=self.state_dir / "host.json",
                call_timeout_s=settings.call_timeout_s,
            )
            self.host.on_restart(self._restore_sessions)
        return self.host

    def _path(self, sid: str) -> Path:
        return process_state.spec_path(self.state_dir, sid, "Claude SDK")

    def _save(self, sid: str) -> None:
        spec = self._specs[sid]
        process_state.write_state(
            self._path(sid),
            {
                "provider": spec.provider,
                "model": spec.model,
                "workspace_id": spec.workspace_id,
                "cwd": spec.cwd,
                "prompt": spec.prompt,
                "reasoning_effort": spec.reasoning_effort,
                "mode_id": spec.mode_id,
                "agent_id": spec.agent_id,
                "runner_harness": spec.runner_harness,
                "handle": self._handles.get(sid),
                "pending_approvals": sorted(self._pending.get(sid, set())),
            },
        )

    def _load(self, ref: SessionRef) -> SessionSpec:
        if ref.session_id in self._specs:
            return self._specs[ref.session_id]
        try:
            value = json.loads(self._path(ref.session_id).read_text(encoding="utf-8"))
            spec = SessionSpec(
                **{
                    key: value[key]
                    for key in SessionSpec.__dataclass_fields__
                    if key in value
                }
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RuntimeError(
                "persisted Claude SDK session metadata is unavailable"
            ) from exc
        if spec.provider != ref.provider:
            raise RuntimeError("persisted Claude SDK provider does not match ref")
        self._specs[ref.session_id] = spec
        handle = value.get("handle")
        if isinstance(handle, str) and handle:
            self._handles[ref.session_id] = handle
        pending = value.get("pending_approvals", [])
        if isinstance(pending, list):
            self._pending[ref.session_id] = {
                item for item in pending if isinstance(item, str)
            }
        return spec

    async def _start_host(self) -> NodeHost:
        host = self._host()
        if host.state == "down":
            await host.start()
        return host

    async def _start_session(
        self, ref: SessionRef, *, prompt: str | None = None
    ) -> None:
        spec = self._specs[ref.session_id]
        host = await self._start_host()
        queue = self._queues.setdefault(ref.session_id, asyncio.Queue())
        previous = self._subscriptions.pop(ref.session_id, None)
        if previous is not None:
            previous.close()
        previous_task = self._tasks.pop(ref.session_id, None)
        if previous_task is not None:
            previous_task.cancel()
        subscription = host.subscribe(ref.session_id)
        self._subscriptions[ref.session_id] = subscription
        self._tasks[ref.session_id] = asyncio.create_task(
            self._read_events(ref, subscription, queue)
        )
        params: dict[str, Any] = {
            "session": ref.session_id,
            "cwd": spec.cwd,
            "model": spec.model,
            "effort": spec.reasoning_effort,
            "mode": spec.mode_id or "auto",
            "prompt": spec.prompt
            if prompt is None and not self._handles.get(ref.session_id)
            else (prompt or ""),
            "env": child_env(spec),
            "stream_idle_timeout_s": self._timeout(),
        }
        if self._handles.get(ref.session_id):
            params["resume_handle"] = self._handles[ref.session_id]
        try:
            result = await host.call("session.start", params)
        except BaseException:
            subscription.close()
            self._tasks.pop(ref.session_id, None)
            raise
        if result.get("session") != ref.session_id:
            raise RuntimeError("Claude SDK host returned a different session id")
        if not isinstance(result.get("resumed"), bool):
            raise TypeError("Claude SDK host returned an invalid resumed state")

    def _timeout(self) -> float:
        from varde_runner.config import config_path, default_toml

        text = self.settings_text
        if text is None:
            path = config_path()
            text = path.read_text(encoding="utf-8") if path.exists() else default_toml()
        return claude_sdk_settings(text)[1]

    async def start(self, spec: SessionSpec) -> SessionRef:
        sid = str(uuid4())
        ref = SessionRef(spec.provider, sid)
        self._specs[sid] = spec
        self._queues[sid] = asyncio.Queue()
        self._save(sid)
        await self._start_session(ref)
        return ref

    async def _read_events(
        self,
        ref: SessionRef,
        subscription: Any,
        queue: asyncio.Queue[RunnerEvent | None],
    ) -> None:
        async for event in subscription:
            if event.event == "handle":
                handle = event.data.get("handle")
                if isinstance(handle, str) and handle:
                    self._handles[ref.session_id] = handle
                    self._save(ref.session_id)
                continue
            if event.event == "exit":
                if event.data.get("reason") == "interrupted":
                    self._interrupted.add(ref.session_id)
                continue
            if event.event in EVENT_KINDS:
                runner_event = RunnerEvent(
                    event.event,
                    ref.session_id,
                    event.data,
                    provider_id=ref.provider,
                )
                if event.event in {"permission_requested", "permission_resolved"}:
                    request_id = event.data.get("request_id")
                    if isinstance(request_id, str):
                        pending = self._pending.setdefault(ref.session_id, set())
                        if event.event == "permission_requested":
                            pending.add(request_id)
                        else:
                            pending.discard(request_id)
                        self._save(ref.session_id)
                if event.event == "permission_requested":
                    runner_event = process_state.without_payload_field(
                        runner_event, "input"
                    )
                if event.event == "tool_intent":
                    runner_event = process_state.redact_tool_input(runner_event)
                queue.put_nowait(runner_event)

    async def _restore_sessions(self) -> None:
        async with self._resuming:
            for sid, spec in tuple(self._specs.items()):
                if sid in self._stopped:
                    continue
                self._expire_pending(sid, spec)
                await self._start_session(SessionRef(spec.provider, sid))

    def _expire_pending(self, sid: str, spec: SessionSpec) -> None:
        queue = self._queues.setdefault(sid, asyncio.Queue())
        for request_id in self._pending.pop(sid, set()):
            queue.put_nowait(
                RunnerEvent(
                    "permission_resolved",
                    sid,
                    {"request_id": request_id, "decision": "expired"},
                    provider_id=spec.provider,
                )
            )
        self._save(sid)

    async def resume(
        self, ref: SessionRef, settings: ResumeSettings | None = None
    ) -> SessionRef:
        spec = self._load(ref)
        if settings and settings.mode_id is not None:
            if settings.mode_id not in SUPPORTED_MODES:
                raise ValueError(f"unsupported Claude SDK mode: {settings.mode_id!r}")
            spec = SessionSpec(
                **{
                    **{
                        key: getattr(spec, key)
                        for key in SessionSpec.__dataclass_fields__
                    },
                    "mode_id": settings.mode_id,
                }
            )
            self._specs[ref.session_id] = spec
            self._save(ref.session_id)
        self._expire_pending(ref.session_id, spec)
        if self.host is not None and self.host.state == "ready":
            try:
                await self.host.call("session.stop", {"session": ref.session_id})
            except Exception:
                logger.debug("old Claude SDK session was already gone", exc_info=True)
        await self._start_session(ref)
        self._interrupted.discard(ref.session_id)
        return ref

    async def send(self, ref: SessionRef, prompt: str) -> None:
        self._load(ref)
        if (
            self.host is None
            or self.host.state != "ready"
            or ref.session_id not in self._tasks
            or ref.session_id in self._interrupted
        ):
            await self.resume(ref)
        try:
            await self._host().call(
                "session.send", {"session": ref.session_id, "text": prompt}
            )
        except Exception:
            if ref.session_id not in self._handles:
                raise
            await self.resume(ref)
            await self._host().call(
                "session.send", {"session": ref.session_id, "text": prompt}
            )

    async def interrupt(self, ref: SessionRef) -> None:
        await self._host().call("session.interrupt", {"session": ref.session_id})
        self._interrupted.add(ref.session_id)

    async def respond_permission(
        self, ref: SessionRef, request_id: str, decision: str
    ) -> None:
        await self._host().call(
            "permission.respond",
            {
                "session": ref.session_id,
                "request_id": request_id,
                "decision": "approve"
                if decision in {"allow", "approve", "approved"}
                else "deny",
            },
        )

    async def idle_status(self, ref: SessionRef) -> str:
        result = await self._host().call("session.alive", {"session": ref.session_id})
        return str(result.get("state", "unknown"))

    def process_alive(self, ref: SessionRef) -> bool:
        task = self._tasks.get(ref.session_id)
        return (
            self.host is not None
            and self.host.state == "ready"
            and task is not None
            and not task.done()
        )

    async def events(self, ref: SessionRef) -> AsyncGenerator[RunnerEvent]:
        queue = self._queues.setdefault(ref.session_id, asyncio.Queue())
        while True:
            event = await queue.get()
            if event is None:
                return
            yield event

    async def stop(self, ref: SessionRef) -> None:
        self._stopped.add(ref.session_id)
        if self.host is not None and self.host.state == "ready":
            await self.host.call("session.stop", {"session": ref.session_id})
        subscription = self._subscriptions.pop(ref.session_id, None)
        if subscription:
            subscription.close()
        task = self._tasks.pop(ref.session_id, None)
        if task:
            task.cancel()
        self._queues.setdefault(ref.session_id, asyncio.Queue()).put_nowait(None)
        self._specs.pop(ref.session_id, None)
        self._handles.pop(ref.session_id, None)
        self._pending.pop(ref.session_id, None)
        self._path(ref.session_id).unlink(missing_ok=True)

    async def close(self) -> None:
        for subscription in self._subscriptions.values():
            subscription.close()
        self._subscriptions.clear()
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        if self.host is not None:
            await self.host.stop()

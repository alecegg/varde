"""Pi Durable adapter over the runner's generic Node host."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import uuid
from collections.abc import AsyncGenerator
from dataclasses import asdict
from pathlib import Path
from typing import Any

from varde_runner.config import Model, PiDurableSettings, adapter_state_root
from varde_runner.events import EventKind, RunnerEvent
from varde_runner.node_host import NodeHost, RestartPolicy
from varde_runner.node_host_config import node_host_engine_path, node_host_settings
from varde_runner.plugins import (
    RunnerCapabilities,
    SessionRef,
    SessionSettings,
    SessionSpec,
    child_environment,
)
from varde_runner.protocol import ResumeSettings

logger = logging.getLogger(__name__)

_EVENT_KINDS: dict[str, EventKind] = {
    "entry_appended": "activity",
    "message": "text",
    "tool_result": "tool_result",
    "usage": "usage",
    "activity": "activity",
    "permission_request": "permission_requested",
    "permission_resolved": "permission_resolved",
}


class PiDurablePlugin:
    config_table = "pi_durable"
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
        settings: PiDurableSettings,
        *,
        config_text: str,
        state_dir: str | Path | None = None,
        host_factory: Any = NodeHost,
    ) -> None:
        self.settings = settings
        self._host_factory = host_factory
        self._host: NodeHost | None = None
        self._state_dir = (
            Path(state_dir) if state_dir else adapter_state_root() / "pi-durable"
        )
        self._state_path = self._state_dir / "sessions.json"
        self._host_state_path = self._state_dir / "host.json"
        self._node = node_host_settings(config_text)
        self._sessions: dict[str, dict[str, Any]] = self._read_state()
        self._leases: dict[str, asyncio.Lock] = {}
        self._started = False

    def session_settings(self, model: Model) -> SessionSettings:
        return SessionSettings(model.model, model.reasoning_effort, model.mode)

    async def start(self, spec: SessionSpec) -> SessionRef:
        await self._validate_key()
        self._validate_mode(spec.mode_id or "workspace-write", spec.role)
        host = await self._ensure_host()
        env = self._session_environment(spec)
        result = await host.call(
            "session.start",
            {
                "cwd": spec.cwd,
                "provider": self.settings.provider,
                "model": spec.model or self.settings.model,
                "role": spec.role,
                "mode": spec.mode_id or "workspace-write",
                "prompt": spec.prompt,
                "env": env,
            },
        )
        session_id = _required_string(result.get("session"), "session")
        ref = SessionRef(spec.provider, session_id)
        self._sessions[session_id] = {
            "provider": ref.provider,
            "session_id": session_id,
            "spec": asdict(spec),
            "cursor": 0,
        }
        self._save_state()
        self._leases.setdefault(session_id, asyncio.Lock())
        return ref

    async def resume(
        self, ref: SessionRef, settings: ResumeSettings | None = None
    ) -> SessionRef:
        host_was_ready = self._host is not None and self._host.state == "ready"
        state = self._state_for(ref)
        spec = SessionSpec(**state["spec"])
        mode = spec.mode_id or "workspace-write"
        if settings is not None and settings.mode_id is not None:
            self._validate_mode(settings.mode_id, spec.role)
            mode = settings.mode_id
        elif settings is not None:
            return ref
        updated = SessionSpec(**{**state["spec"], "mode_id": mode})
        state["spec"] = asdict(updated)
        self._save_state()
        await self._validate_key()
        if host_was_ready:
            await self._start_existing(ref, updated)
        else:
            await self._ensure_host()
        return ref

    async def _start_existing(self, ref: SessionRef, spec: SessionSpec) -> None:
        await self._validate_key()
        await self._ensure_host()
        host = self._host
        if host is None:
            raise RuntimeError("Pi Durable Node host did not start")
        await host.call(
            "session.start",
            {
                "cwd": spec.cwd,
                "provider": self.settings.provider,
                "model": spec.model or self.settings.model,
                "role": spec.role,
                "mode": spec.mode_id or "workspace-write",
                "conversation": ref.session_id,
                "env": self._session_environment(spec),
            },
        )

    async def send(self, ref: SessionRef, prompt: str) -> None:
        await self.send_with_id(ref, prompt, uuid.uuid4().hex)

    async def send_with_id(self, ref: SessionRef, prompt: str, request_id: str) -> None:
        lease = self._leases.setdefault(ref.session_id, asyncio.Lock())
        async with lease:
            host = await self._ensure_host()
            await host.call(
                "session.send",
                {
                    "session": ref.session_id,
                    "text": prompt,
                    "requestId": _required_string(request_id, "request_id"),
                },
            )

    async def interrupt(self, ref: SessionRef) -> None:
        lease = self._leases.setdefault(ref.session_id, asyncio.Lock())
        async with lease:
            host = await self._ensure_host()
            await host.call("session.interrupt", {"session": ref.session_id})

    async def respond_permission(
        self, ref: SessionRef, request_id: str, decision: str
    ) -> None:
        translated = {"approve": "approved", "deny": "denied"}.get(decision)
        if translated is None:
            raise ValueError("decision must be approve or deny")
        lease = self._leases.setdefault(ref.session_id, asyncio.Lock())
        async with lease:
            host = await self._ensure_host()
            await host.call(
                "permission.respond",
                {"approval_id": request_id, "decision": translated},
            )

    async def stop(self, ref: SessionRef) -> None:
        if ref.session_id not in self._sessions:
            return
        lease = self._leases.setdefault(ref.session_id, asyncio.Lock())
        async with lease:
            host = await self._ensure_host()
            await host.call("session.stop", {"session": ref.session_id})
        self._sessions.pop(ref.session_id, None)
        self._leases.pop(ref.session_id, None)
        self._save_state()

    async def idle_status(self, ref: SessionRef) -> str:
        host = await self._ensure_host()
        result = await host.call("session.alive", {"session": ref.session_id})
        return "running" if result.get("state") == "running" else "idle"

    def process_alive(self, _ref: SessionRef) -> bool:
        return self._host is not None and self._host.state != "down"

    async def usage(self, ref: SessionRef) -> dict[str, Any]:
        host = await self._ensure_host()
        result = await host.call("usage.get", {"session": ref.session_id})
        return {"source": "pi-durable", "models": result.get("models", [])}

    async def events(self, ref: SessionRef) -> AsyncGenerator[RunnerEvent]:
        state = self._state_for(ref)
        cursor = state["cursor"]
        while True:
            host = await self._ensure_host()
            subscription = host.subscribe(ref.session_id)
            await host.call(
                "events.subscribe",
                {"session": ref.session_id, "after_cursor": cursor},
            )
            last_activity = asyncio.get_running_loop().time()
            silent_sent = False
            try:
                while True:
                    timeout = max(
                        0.05,
                        self.settings.stream_idle_timeout_s
                        - (asyncio.get_running_loop().time() - last_activity),
                    )
                    try:
                        frame = await asyncio.wait_for(anext(subscription), timeout)
                    except TimeoutError:
                        status = await self.idle_status(ref)
                        if status == "running" and not silent_sent:
                            silent_sent = True
                            yield RunnerEvent(
                                "status",
                                ref.session_id,
                                {"status": "running", "silent": True},
                                "pi-durable",
                            )
                        continue
                    except StopAsyncIteration:
                        break
                    last_activity = asyncio.get_running_loop().time()
                    if silent_sent:
                        yield RunnerEvent(
                            "status",
                            ref.session_id,
                            {"status": "running", "silent": False},
                            "pi-durable",
                        )
                    silent_sent = False
                    event = _runner_event(frame, ref.session_id)
                    if event is None:
                        continue
                    cursor_value = event.payload.pop("cursor", None)
                    if cursor_value is not None:
                        cursor = cursor_value
                    yield event
                    state["cursor"] = cursor
                    self._save_state()
            finally:
                subscription.close()

    async def close(self) -> None:
        if self._host is not None:
            await self._host.stop()
            self._host = None
        self._started = False

    async def _ensure_host(self) -> NodeHost:
        if self._host is not None:
            while self._host.state in {"starting", "restarting"}:
                await asyncio.sleep(0.05)
            if self._host.state == "ready":
                return self._host
            await self._host.stop()
            self._host = None
        self._state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        storage_dir = self._storage_dir()
        storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        env = child_environment()
        env["VARDE_PI_DURABLE_STORAGE_DIR"] = str(storage_dir)
        engine_path = node_host_engine_path("durable")
        host_script = engine_path.parents[2] / "host.mjs"
        host = self._host_factory(
            [self._node.node, str(host_script)],
            engine_path,
            env,
            policy=RestartPolicy(self._node.restart_max, self._node.restart_window_s),
            state_path=self._host_state_path,
            call_timeout_s=self._node.call_timeout_s,
        )
        host.on_restart(self._restore_sessions)
        await host.start()
        self._host = host
        self._started = True
        if self._sessions:
            await self._restore_sessions()
        return host

    async def _restore_sessions(self) -> None:
        host = self._host
        if host is None:
            return
        for session_id, state in list(self._sessions.items()):
            ref = SessionRef(state["provider"], session_id)
            spec = SessionSpec(**state["spec"])
            await host.call(
                "session.start",
                {
                    "cwd": spec.cwd,
                    "provider": self.settings.provider,
                    "model": spec.model or self.settings.model,
                    "role": spec.role,
                    "mode": spec.mode_id or "workspace-write",
                    "conversation": session_id,
                    "env": self._session_environment(spec),
                },
            )
            self._leases.setdefault(ref.session_id, asyncio.Lock())

    def _session_environment(self, spec: SessionSpec) -> dict[str, str]:
        env = child_environment()
        env.update(
            {
                "VARDE_AGENT_ID": spec.agent_id or spec.workspace_id,
                "VARDE_HARNESS": "pi-durable",
            }
        )
        return env

    async def _validate_key(self) -> None:
        key_env = self.settings.key_env
        if key_env and not os.environ.get(key_env):
            raise RuntimeError(
                f"Pi Durable API key is missing from environment variable {key_env}"
            )

    @staticmethod
    def _validate_mode(mode: str, role: str) -> None:
        if mode not in {"read-only", "workspace-write"}:
            raise ValueError(f"Pi Durable does not support mode {mode}")
        if role in {"explorer", "reviewer"} and mode != "read-only":
            raise ValueError(f"Pi Durable {role} role must use read-only mode")

    def _storage_dir(self) -> Path:
        configured = Path(self.settings.storage_dir).expanduser()
        root = adapter_state_root().resolve()
        path = (
            configured.resolve()
            if configured.is_absolute()
            else (root / configured).resolve()
        )
        if not path.is_relative_to(root):
            raise ValueError("pi_durable.storage_dir must be under the Varde data root")
        return path

    def _state_for(self, ref: SessionRef) -> dict[str, Any]:
        state = self._sessions.get(ref.session_id)
        if state is None or state["provider"] != ref.provider:
            raise RuntimeError(f"unknown Pi Durable session: {ref.session_id}")
        return state

    def _read_state(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self._state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(value, dict) or not all(
            isinstance(item, dict) for item in value.values()
        ):
            raise RuntimeError("Pi Durable session state is invalid")
        return value

    def _save_state(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix="sessions-", dir=self._state_dir)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self._sessions, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._state_path)
            os.chmod(self._state_path, 0o600)
        finally:
            Path(temporary).unlink(missing_ok=True)


def _required_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be a non-empty string")
    return value


def _runner_event(frame: Any, session_id: str) -> RunnerEvent | None:
    name = frame.event
    payload = dict(frame.data)
    mapped = _EVENT_KINDS.get(name)
    if mapped == "text":
        if payload.get("role") != "assistant":
            return None
        calls = [
            part
            for part in payload.get("content", [])
            if isinstance(part, dict) and part.get("type") == "toolCall"
        ]
        if calls:
            call = calls[0]
            payload = {
                "call_id": call.get("id") or payload.get("toolCallId"),
                "name": call.get("name"),
                "status": "running",
                "input": call.get("arguments", {}),
                "cursor": payload.get("cursor"),
            }
            return RunnerEvent("tool_intent", session_id, payload, "pi-durable")
        text = "".join(
            part.get("text", "")
            for part in payload.get("content", [])
            if isinstance(part, dict) and part.get("type") == "text"
        )
        payload = {
            "text": text,
            **{key: value for key, value in payload.items() if key != "content"},
        }
        if not text:
            return None
    elif mapped == "tool_result":
        payload = {
            "call_id": payload.get("toolCallId"),
            "status": "completed",
            "content": payload.get("content"),
        }
    elif mapped in {"permission_requested", "permission_resolved"}:
        payload["request_id"] = payload.pop("approval_id", None)
    elif mapped is None:
        return None
    return RunnerEvent(mapped, session_id, payload, "pi-durable")

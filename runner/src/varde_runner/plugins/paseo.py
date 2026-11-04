"""Paseo SDK adapter backed by the pinned Node sidecar."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import uuid
from collections import Counter, deque
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any, Literal

from varde_runner.agent_log import (
    TOOL_INTENT,
    TOOL_RESULT,
    tool_intent_payload,
    tool_result_payload,
)
from varde_runner.config import KNOWN_MODES, Model
from varde_runner.events import RunnerEvent
from varde_runner.plugins import (
    RunnerCapabilities,
    SessionRef,
    SessionSettings,
    SessionSpec,
)

HARNESS_TO_PASEO_PROVIDER = {
    "codex-app-server": "codex",
    "pi": "pi",
    "claude-sdk": "claude",
}
PASEO_MODE_MAP = {
    "codex": {
        "auto": "auto",
        "workspace-write": "auto",
        "full-access": "full-access",
        "danger-full-access": "full-access",
    },
    "pi": {
        "auto": "auto",
        "read-only": "read-only",
        "workspace-write": "workspace-write",
        "full-access": "full-access",
        "danger-full-access": "danger-full-access",
    },
    "claude": {
        "auto": "auto",
        "read-only": "plan",
        "workspace-write": "acceptEdits",
        "full-access": "bypassPermissions",
        "danger-full-access": "bypassPermissions",
    },
}


class PaseoRequestError(RuntimeError):
    def __init__(self, message: str, session_id: str | None = None) -> None:
        super().__init__(message)
        self.session_id = session_id


class PaseoPlugin:
    capabilities = RunnerCapabilities(
        resume=True,
        permission_commands=True,
        usage=True,
        idle_status=True,
        persistent_process=True,
        respond=True,
    )

    @staticmethod
    def harness_for_provider(provider: str) -> str:
        for harness, mapped_provider in HARNESS_TO_PASEO_PROVIDER.items():
            if mapped_provider == provider:
                return harness
        return provider

    @staticmethod
    def provider_for_harness(harness: str) -> str:
        try:
            return HARNESS_TO_PASEO_PROVIDER[harness]
        except KeyError as exc:
            raise ValueError(f"unsupported runner harness: {harness}") from exc

    @classmethod
    def session_settings(cls, model: Model) -> SessionSettings:
        provider = cls.provider_for_harness(model.harness)
        if re.search(r"(?:^|[-/])sol(?:$|[-/])", model.model):
            raise ValueError("sol models are prohibited")
        mode = model.mode
        if mode is None:
            return SessionSettings(model.model, model.reasoning_effort)
        if mode not in KNOWN_MODES:
            raise ValueError(f"unsupported runner mode: {model.mode}")
        if mode not in PASEO_MODE_MAP[provider]:
            raise ValueError(
                f"runner mode {mode!r} has no Paseo equivalent for provider "
                f"{provider!r}"
            )
        return SessionSettings(
            model=model.model,
            reasoning_effort=model.reasoning_effort,
            mode_id=PASEO_MODE_MAP[provider][mode],
        )

    def is_provider_limit_error(self, error: BaseException) -> bool:
        return is_provider_limit_error(error)

    def __init__(
        self,
        socket_path: Path,
        url: str,
        sidecar_command: Sequence[str] | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.url = url
        sidecar = Path(__file__).parents[3] / "sidecar" / "index.mjs"
        self._client_package = sidecar.parent / "node_modules" / "@getpaseo" / "client"
        self._sidecar_command = tuple(sidecar_command or ("node", str(sidecar)))
        self._server: asyncio.AbstractServer | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._events: dict[str, asyncio.Queue[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=20)
        self._ready = asyncio.Event()
        self._start_lock = asyncio.Lock()

    @classmethod
    def from_environment(cls) -> PaseoPlugin:
        return cls(
            Path(
                os.environ.get(
                    "VARDE_RUNNER_SOCKET",
                    Path(tempfile.gettempdir())
                    / f"varde-runner-{uuid.uuid4().hex}.sock",
                )
            ),
            os.environ.get("PASEO_URL", "ws://127.0.0.1:6767/ws"),
        )

    async def _ensure_started(self) -> None:
        async with self._start_lock:
            if not self._client_package.is_dir():
                raise RuntimeError(
                    "Paseo sidecar dependency is missing at "
                    f"{self._client_package}. Run `npm ci --prefix runner/sidecar` "
                    "from the repository root."
                )
            if self._server is None:
                self.socket_path.parent.mkdir(parents=True, exist_ok=True)
                self.socket_path.unlink(missing_ok=True)
                self._server = await asyncio.start_unix_server(
                    self._accept, path=self.socket_path, limit=2 * 1024 * 1024
                )
            process = self._process
            if process and process.returncode is None and self._ready.is_set():
                return
            if process and process.returncode is None:
                process.terminate()
                await process.wait()
            self._ready.clear()
            self._writer = None
            self._process = await asyncio.create_subprocess_exec(
                *self._sidecar_command,
                str(self.socket_path),
                self.url,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            process = self._process
            if process.stderr:
                self._stderr_task = asyncio.create_task(
                    self._drain_stderr(process.stderr)
                )
            asyncio.create_task(self._watch_process(process))
            try:
                await asyncio.wait_for(self._ready.wait(), timeout=10)
            except TimeoutError as exc:
                await self._disconnect()
                detail = "; ".join(self._stderr_tail)
                suffix = f": {detail}" if detail else ""
                raise RuntimeError(f"Paseo sidecar failed to connect{suffix}") from exc

    async def _accept(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        old_writer = self._writer
        if old_writer and old_writer is not writer and not old_writer.is_closing():
            old_writer.close()
        self._writer = writer
        self._ready.set()
        self._reader_task = asyncio.create_task(self._read_messages(reader, writer))

    async def _read_messages(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while line := await reader.readline():
                try:
                    message = json.loads(line)
                except json.JSONDecodeError, UnicodeDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                if "event" in message:
                    self._queue_event(message)
                    continue
                request_id = message.get("id")
                if not isinstance(request_id, str):
                    continue
                future = self._pending.pop(request_id, None)
                if future and not future.done():
                    future.set_result(message)
        except ConnectionError, OSError:
            pass
        finally:
            await self._disconnect(writer)

    async def _watch_process(self, process: asyncio.subprocess.Process) -> None:
        await process.wait()
        if self._process is process:
            await self._disconnect()

    async def _drain_stderr(self, reader: asyncio.StreamReader) -> None:
        while line := await reader.readline():
            self._stderr_tail.append(line.decode(errors="replace").rstrip())

    def _queue_event(self, message: dict[str, Any]) -> None:
        queue = self._event_queue(message["session_id"])
        if queue.full():
            while not queue.empty():
                queue.get_nowait()
            message = {
                "session_id": message["session_id"],
                "event": "error",
                "payload": {"message": "Paseo event queue overflow; events were lost"},
            }
        queue.put_nowait(message)

    def _event_queue(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        return self._events.setdefault(session_id, asyncio.Queue(maxsize=1024))

    async def _disconnect(self, writer: asyncio.StreamWriter | None = None) -> None:
        if writer is not None and self._writer is not writer:
            return
        current = self._writer
        self._writer = None
        self._ready.clear()
        if current and not current.is_closing():
            current.close()
        error = RuntimeError("Paseo sidecar disconnected")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()

    async def _request(self, operation: str, **payload: Any) -> dict[str, Any]:
        await self._ensure_started()
        writer = self._writer
        if not writer or not self._ready.is_set():
            raise RuntimeError("Paseo sidecar is disconnected")
        request_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            writer.write(
                (
                    json.dumps({"id": request_id, "op": operation, **payload}) + "\n"
                ).encode()
            )
            await writer.drain()
        except (ConnectionError, OSError) as exc:
            self._pending.pop(request_id, None)
            await self._disconnect(writer)
            raise RuntimeError("Paseo sidecar disconnected") from exc
        response = await future
        if response.get("error"):
            raise PaseoRequestError(response["error"], response.get("session_id"))
        return response

    async def start(self, spec: SessionSpec) -> SessionRef:
        if not spec.workspace_id:
            raise ValueError("an existing workspace_id is required")
        response = await self._request(
            "start",
            workspace_id=spec.workspace_id,
            cwd=spec.cwd,
            provider_model=f"{spec.provider}/{spec.model}",
            reasoning_effort=spec.reasoning_effort,
            **({"mode_id": spec.mode_id} if spec.mode_id else {}),
            prompt=spec.prompt,
        )
        return SessionRef("paseo", response["session_id"])

    async def open_workspace(self, cwd: str) -> str:
        response = await self._request("open_workspace", cwd=cwd)
        return response["workspace_id"]

    async def resume(self, ref: SessionRef) -> SessionRef:
        await self._request("resume", session_id=ref.session_id)
        return ref

    async def send(self, ref: SessionRef, prompt: str) -> None:
        await self._request("send", session_id=ref.session_id, prompt=prompt)

    async def inspect(self, ref: SessionRef) -> dict[str, Any]:
        """Return the daemon's current public session snapshot."""
        return await self._request("inspect", session_id=ref.session_id)

    async def list_agents(self) -> list[dict[str, Any]]:
        """Return the current Paseo agent directory without changing it."""
        response = await self._request("list_agents")
        agents = response.get("agents", [])
        return agents if isinstance(agents, list) else []

    async def list_workspaces(self) -> list[dict[str, str]]:
        """Return unique workspaces present in the Paseo agent directory."""
        response = await self._request("list_workspaces")
        workspaces = response.get("workspaces", [])
        return workspaces if isinstance(workspaces, list) else []

    async def idle_status(self, ref: SessionRef) -> str:
        """Return a normalized status suitable for idle-gated delivery."""
        status = (await self.inspect(ref)).get("status")
        return status if status in {"idle", "running", "error"} else "unknown"

    async def respond_permission(
        self, ref: SessionRef, request_id: str, decision: str
    ) -> None:
        await self._request(
            "permission",
            session_id=ref.session_id,
            request_id=request_id,
            decision=decision,
        )

    async def stop(self, ref: SessionRef) -> None:
        await self._request("stop", session_id=ref.session_id)

    async def events(self, ref: SessionRef) -> AsyncGenerator[RunnerEvent]:
        queue = self._event_queue(ref.session_id)
        response = await self._request("subscribe", session_id=ref.session_id)
        seen_refs: set[str] = set()
        snapshot_events: Counter[str] = Counter()
        for item in response.get("snapshot", []):
            event = _normalize(ref.session_id, item)
            if event.raw_event_ref:
                seen_refs.add(event.raw_event_ref)
            snapshot_events[_event_signature(event)] += 1
            yield event
        while not queue.empty():
            message = queue.get_nowait()
            raw_ref = message.get("raw_event_ref")
            if raw_ref and raw_ref in seen_refs:
                continue
            event = _normalize(ref.session_id, message)
            signature = _event_signature(event)
            if snapshot_events[signature]:
                snapshot_events[signature] -= 1
                continue
            if raw_ref:
                seen_refs.add(raw_ref)
            yield event
        while True:
            message = await queue.get()
            raw_ref = message.get("raw_event_ref")
            if raw_ref and raw_ref in seen_refs:
                continue
            if raw_ref:
                seen_refs.add(raw_ref)
            yield _normalize(ref.session_id, message)

    async def close(self) -> None:
        await self._disconnect()
        process = self._process
        if process and process.returncode is None:
            process.terminate()
            await process.wait()
        self._process = None
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        self.socket_path.unlink(missing_ok=True)
        self._server = None
        if self._stderr_task:
            await self._stderr_task
            self._stderr_task = None
        self._reader_task = None


def _paseo_tool_event(
    payload: Any,
) -> tuple[Literal["tool_intent", "tool_result"], dict[str, Any]] | None:
    """Map a Paseo tool_call item to a neutral event kind and payload."""
    item = payload.get("item") if isinstance(payload, dict) else None
    if not isinstance(item, dict) or item.get("type") != "tool_call":
        return None
    call_id, status = item.get("callId"), item.get("status")
    if not isinstance(call_id, str) or not call_id:
        return None
    tool = item.get("name")
    if status == "running":
        return TOOL_INTENT, tool_intent_payload(call_id, tool, status, payload)
    if status in {"completed", "failed", "canceled"}:
        return TOOL_RESULT, tool_result_payload(call_id, tool, status, payload)
    return None


def _normalize(session_id: str, raw: dict[str, Any]) -> RunnerEvent:
    kind = raw.get("event")
    payload = raw.get("payload", {})
    if kind == "tool":
        mapped = _paseo_tool_event(payload)
        if mapped is not None:
            kind, payload = mapped
    if kind == "status":
        status = payload.get("status")
        if status not in {"idle", "running", "error"}:
            status = "error"
        payload = {**payload, "status": status}
    if kind not in {
        "status",
        "text",
        "tool",
        TOOL_INTENT,
        TOOL_RESULT,
        "usage",
        "permission_requested",
        "permission_resolved",
        "session_end",
        "error",
    }:
        original_kind = kind
        kind = "error"
        payload = {"message": f"unsupported Paseo event: {original_kind}"}
    return RunnerEvent(
        kind=kind,
        session_id=session_id,
        payload=payload,
        provider_id="paseo",
        raw_event_ref=raw.get("raw_event_ref"),
    )


def _event_signature(event: RunnerEvent) -> str:
    return json.dumps([event.kind, event.payload], sort_keys=True, default=str)


def is_provider_limit_error(error: Any) -> bool:
    """Recognize the observed "hit your usage limit" provider error."""
    if isinstance(error, BaseException):
        if error.args and isinstance(error.args[0], dict):
            return is_provider_limit_error(error.args[0])
        error = str(error)
    if isinstance(error, dict):
        details = error.get("error", error)
        if isinstance(details, dict):
            code = str(details.get("type") or details.get("code") or "").casefold()
            if code in {
                "usage_limit_exceeded",
                "quota_exceeded",
            }:
                return True
            message = details.get("message")
            return (
                isinstance(message, str)
                and "hit your usage limit" in message.casefold()
            )
    return isinstance(error, str) and "hit your usage limit" in error.casefold()

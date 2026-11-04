"""Codex app-server adapter using JSON-RPC over stdio."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import tempfile
import time
import uuid
from collections import deque
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, ClassVar, NoReturn

from varde_runner.config import Model, adapter_state_root
from varde_runner.diagnostic import StartupTimeout
from varde_runner.events import EventKind, RunnerEvent
from varde_runner.plugins import (
    RunnerCapabilities,
    SessionRef,
    SessionSettings,
    SessionSpec,
    child_environment,
    process_state,
)
from varde_runner.plugins.codex_app_server import wire
from varde_runner.protocol import ResumeSettings

ProcessIdentity = process_state.ProcessIdentity
logger = logging.getLogger(__name__)
MAX_STDOUT_LINE_BYTES = 16 * 1024 * 1024


def child_env(spec: SessionSpec) -> dict[str, str]:
    env = child_environment()
    env.update(
        {
            "VARDE_AGENT_ID": spec.agent_id or spec.workspace_id,
            "VARDE_HARNESS": "codex-app-server",
        }
    )
    return env


@dataclass
class _Session:
    spec: SessionSpec | None = None
    status: str | None = None
    stderr: deque[str] | None = None
    process: asyncio.subprocess.Process | None = None
    queue: asyncio.Queue[RunnerEvent | None] | None = None
    reader: asyncio.Task[None] | None = None
    stderr_reader: asyncio.Task[None] | None = None
    pending: set[str] = field(default_factory=set)
    permission_inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    answered: set[str] = field(default_factory=set)
    thread_id: str | None = None
    turn_id: str | None = None
    request_kinds: dict[str | int, str] = field(default_factory=dict)
    turn_started: asyncio.Future[str] | None = None
    turn_start_request_id: str | None = None
    turn_started_at: float | None = None
    first_text_ms: int | None = None
    malformed_stdout_count: int = 0
    malformed_stdout_reported: bool = False
    terminal_pending_approval: str | None = None


def _schema_method_names(value: Any) -> set[str]:
    if isinstance(value, dict):
        names = {key for key in value if isinstance(key, str)}
        for child in value.values():
            names.update(_schema_method_names(child))
        return names
    if isinstance(value, list):
        return set().union(*(_schema_method_names(child) for child in value))
    return {value} if isinstance(value, str) else set()


def _inspect_process(pid: int, _command: list[str]) -> ProcessIdentity | None:
    return process_state.inspect_process(pid, "Codex")


def _process_group_exists(process_group: int) -> bool:
    return process_state.process_group_exists(process_group)


class CodexAppServerPlugin:
    config_table = "codex_app_server"
    _TURN_STARTED_TIMEOUT: float = 10
    _probe_cache: ClassVar[dict[tuple[str, int], tuple[str, ...] | str]] = {}
    capabilities = RunnerCapabilities(
        resume=True,
        guard_read_only=True,
        permission_commands=True,
        usage=True,
        idle_status=True,
        persistent_process=True,
        steer=True,
        interrupt=True,
        respond=True,
    )

    def __init__(  # noqa: PLR0913 - process inspection and signaling are injected test seams.
        self,
        executable: str | Path | None = None,
        *,
        interrupt_timeout: float = 4.0,
        stop_timeout: float = 2.0,
        state_dir: str | Path | None = None,
        process_inspector: Callable[
            [int, list[str]], ProcessIdentity | None
        ] = _inspect_process,
        process_group_exists: Callable[[int], bool] = _process_group_exists,
        process_group_signal: Callable[[int, int], None] = os.killpg,
    ) -> None:
        self.executable = str(executable) if executable else shutil.which("codex")
        self.interrupt_timeout = interrupt_timeout
        self.stop_timeout = stop_timeout
        self.process_inspector = process_inspector
        self.process_group_exists = process_group_exists
        self.process_group_signal = process_group_signal
        self.state_dir = (
            Path(state_dir)
            if state_dir
            else (adapter_state_root() / "codex-app-server")
        )
        self._sessions: dict[str, _Session] = {}
        self._stopping_pids: set[int] = set()
        self._rpc_methods: dict[str | int, str] = {}
        self._rpc_waiters: dict[str | int, asyncio.Future[dict[str, Any]]] = {}
        self._rpc_sessions: dict[str | int, str] = {}
        self._restarting: set[str] = set()
        self._next_request_id = 1
        self._probed = False

    def session_settings(self, model: Model) -> SessionSettings:
        return SessionSettings(model.model, model.reasoning_effort, model.mode)

    def is_provider_limit_error(self, exc: BaseException) -> bool:
        details: Any = exc.args[0] if exc.args else str(exc)
        if isinstance(details, dict):
            nested = details.get("error", details)
            if isinstance(nested, dict):
                code = str(nested.get("type") or nested.get("code") or "").casefold()
                message = str(nested.get("message") or "").casefold()
                return code in {"usage_limit_exceeded", "quota_exceeded"} or (
                    "hit your usage limit" in message
                )
        text = str(details).casefold()
        return "usage_limit_exceeded" in text or "hit your usage limit" in text

    async def start(self, spec: SessionSpec) -> SessionRef:
        if not self.executable:
            raise RuntimeError("codex executable not found on PATH")
        await self._probe()
        session_id = str(uuid.uuid4())
        ref = SessionRef(spec.provider, session_id)
        self._initialize_session(session_id)
        self._sessions[session_id].spec = spec
        try:
            self._persist_spec(session_id, spec)
            await self._spawn(ref, None)
            if spec.prompt:
                await self.send(ref, spec.prompt)
        except BaseException:
            await self.stop(ref)
            self._remove_spec(session_id)
            self._clear_live_state(session_id)
            raise
        return ref

    async def run_guard(self, spec: SessionSpec) -> str | None:
        """Run one bounded guard turn and discard its temporary session state."""
        ref = await self.start(spec)
        try:
            response = []
            async for event in self.events(ref):
                if event.kind == "text":
                    text = event.payload.get("text")
                    if isinstance(text, str):
                        response.append(text)
                elif event.kind == "error":
                    return None
                elif event.kind == "session_end":
                    if event.payload.get("status") != "completed":
                        return None
                    return "".join(response)
            return None
        finally:
            try:
                await self.stop(ref)
            finally:
                self._remove_spec(ref.session_id)
                self._clear_live_state(ref.session_id)

    async def _probe(self) -> None:
        if self._probed:
            return
        executable = self.executable
        if executable is None:
            self._raise_probe_error("codex executable not found on PATH")
        binary = str(Path(executable).expanduser().resolve())
        try:
            cache_key = (binary, Path(binary).stat().st_mtime_ns)
        except OSError as exc:
            self._raise_probe_error(f"Codex executable is unavailable: {exc}")
        cached = self._probe_cache.get(cache_key)
        if cached is None:
            try:
                cached = await self._probe_binary(binary)
            except (RuntimeError, ValueError) as exc:
                message = str(exc)
                if isinstance(exc, ValueError):
                    message = f"Codex version could not be parsed: {message}"
                self._probe_cache[cache_key] = message
                self._raise_probe_error(message)
            self._probe_cache[cache_key] = cached
        if isinstance(cached, str):
            self._raise_probe_error(cached)
        if cached:
            self._raise_probe_error(
                f"Codex schema is missing required methods: {', '.join(cached)}"
            )
        self._probed = True

    async def _probe_binary(self, binary: str) -> tuple[str, ...]:
        version_stdout, _ = await self._run_probe_command(
            [binary, "--version"], timeout=5
        )
        version_text = version_stdout.decode(errors="replace").strip()
        if not wire.version_at_least(version_text, wire.MINIMUM_VERSION):
            self._raise_probe_error(
                f"Codex version {version_text or 'unknown'} is below required "
                f"{wire.MINIMUM_VERSION}"
            )
        with tempfile.TemporaryDirectory(prefix="varde-codex-schema-") as directory:
            await self._run_probe_command(
                [binary, "app-server", "generate-json-schema", "--out", directory],
                timeout=15,
            )
            return self._missing_schema_methods(Path(directory))

    @staticmethod
    def _raise_probe_error(message: str) -> NoReturn:
        raise RuntimeError(message)

    @staticmethod
    async def _run_probe_command(
        command: list[str], *, timeout: float
    ) -> tuple[bytes, bytes]:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise StartupTimeout(f"Codex probe timed out: {command[1]}") from None
        if process.returncode:
            detail = stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"Codex probe failed ({command[1]}): {detail or process.returncode}"
            )
        return stdout, stderr

    @staticmethod
    def _schema_methods(path: Path) -> set[str]:
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                f"Codex schema file is unavailable: {path.name}"
            ) from exc
        return _schema_method_names(schema) & set(wire.REQUIRED_METHODS)

    @classmethod
    def _missing_schema_methods(cls, directory: Path) -> tuple[str, ...]:
        client = cls._schema_methods(directory / "ClientRequest.json")
        client.update(cls._schema_methods(directory / "ClientNotification.json"))
        server = cls._schema_methods(directory / "ServerRequest.json")
        server.update(cls._schema_methods(directory / "ServerNotification.json"))
        return wire.missing_methods(client, server)

    def _session_status(self, session_id: str) -> str | None:
        session = self._sessions.get(session_id)
        return session.status if session is not None else None

    def _session_queue(self, session_id: str) -> asyncio.Queue[RunnerEvent | None]:
        queue = self._sessions[session_id].queue
        if queue is None:
            raise KeyError(session_id)
        return queue

    def _initialize_session(self, session_id: str) -> None:
        session = self._sessions.setdefault(session_id, _Session())
        if session.queue is None:
            session.queue = asyncio.Queue()
        session.pending = set()
        session.permission_inputs = {}
        session.answered = set()
        session.stderr = deque(maxlen=20)
        session.status = "idle"
        session.request_kinds = {}

    def _spec_path(self, session_id: str) -> Path:
        return process_state.spec_path(self.state_dir, session_id, "Codex")

    def _persist_spec(self, session_id: str, spec: SessionSpec) -> None:
        process_state.persist_spec(self._spec_path(session_id), spec)

    def _load_spec(self, ref: SessionRef) -> SessionSpec:
        session = self._sessions.get(ref.session_id)
        spec = session.spec if session is not None else None
        if spec is not None:
            return spec
        try:
            value = json.loads(self._spec_path(ref.session_id).read_text())
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"cannot restore Codex session {ref.session_id}: persisted session "
                "metadata is unavailable"
            ) from exc
        if not isinstance(value, dict):
            raise TypeError("persisted Codex session metadata must be an object")
        try:
            fields = SessionSpec.__dataclass_fields__
            spec = SessionSpec(**{key: value[key] for key in fields if key in value})
        except TypeError as exc:
            raise RuntimeError("persisted Codex session metadata is invalid") from exc
        if spec.provider != ref.provider:
            raise RuntimeError("persisted Codex session provider does not match ref")
        if session is None:
            session = self._sessions.setdefault(ref.session_id, _Session())
        session.spec = spec
        return spec

    def _remove_spec(self, session_id: str) -> None:
        with contextlib.suppress(RuntimeError):
            self._spec_path(session_id).unlink(missing_ok=True)

    def remove_spec(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            session.spec = None
        self._remove_spec(session_id)

    async def _spawn(self, ref: SessionRef, resume_id: str | None) -> None:
        spec = self._sessions[ref.session_id].spec
        if spec is None:
            raise RuntimeError("Codex session specification is unavailable")
        command = wire.build_command(spec.mode_id or "auto", spec.model or None)
        command[0] = self.executable or command[0]
        env = child_env(spec)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=spec.cwd,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                limit=MAX_STDOUT_LINE_BYTES,
            )
        except OSError as exc:
            raise RuntimeError("Codex executable could not be started") from exc
        self._sessions[ref.session_id].process = process
        identity = self.process_inspector(process.pid, command)
        if identity is None:
            raise RuntimeError("Codex process identity could not be inspected")
        self._persist_process(ref.session_id, process.pid, command, identity)
        self._sessions[ref.session_id].stderr_reader = asyncio.create_task(
            self._drain_stderr(ref.session_id, process)
        )
        self._sessions[ref.session_id].reader = asyncio.create_task(
            self._read(ref, process)
        )
        await self._rpc(ref, wire.encode_initialize("0.1.0", self._id()), "initialize")
        await self._write(ref, wire.encode_initialized())
        if resume_id:
            raw = wire.encode_thread_resume(
                resume_id,
                spec.mode_id or "auto",
                spec.cwd,
                spec.model or None,
                self._id(),
            )
            method = "thread/resume"
        else:
            raw = wire.encode_thread_start(
                spec.cwd, spec.mode_id or "auto", spec.model or None, self._id()
            )
            method = "thread/start"
        result = (await self._rpc(ref, raw, method)).get("result")
        thread = result.get("thread") if isinstance(result, dict) else None
        thread_id = thread.get("id") if isinstance(thread, dict) else None
        if not isinstance(thread_id, str):
            raise TypeError("Codex did not return a thread id")
        self._sessions[ref.session_id].thread_id = thread_id
        self._persist_thread_id(ref.session_id, thread_id)

    def _id(self) -> str:
        current = f"varde-{self._next_request_id}"
        self._next_request_id += 1
        return current

    async def _write(self, ref: SessionRef, message: str) -> None:
        process = self._live_process(ref)
        if process.stdin is None:
            raise RuntimeError("Codex app-server stdin pipe is unavailable")
        process.stdin.write((message + "\n").encode())
        await process.stdin.drain()

    async def _rpc(self, ref: SessionRef, message: str, method: str) -> dict[str, Any]:
        frame = json.loads(message)
        request_id = frame["id"]
        future = asyncio.get_running_loop().create_future()
        self._rpc_waiters[request_id] = future
        self._rpc_methods[request_id] = method
        self._rpc_sessions[request_id] = ref.session_id
        try:
            await self._write(ref, message)
            return await asyncio.wait_for(future, 10)
        finally:
            self._rpc_waiters.pop(request_id, None)
            self._rpc_methods.pop(request_id, None)
            self._rpc_sessions.pop(request_id, None)

    async def _drain_stderr(
        self, session_id: str, process: asyncio.subprocess.Process
    ) -> None:
        if process.stderr is None:
            raise RuntimeError("Codex process stderr pipe is unavailable")
        while line := await process.stderr.readline():
            stderr = self._sessions[session_id].stderr
            if stderr is not None:
                stderr.append(line.decode(errors="replace").rstrip())

    async def _read(self, ref: SessionRef, process: asyncio.subprocess.Process) -> None:
        if process.stdout is None:
            raise RuntimeError("Codex stdout unavailable")
        session_id = ref.session_id
        queue = self._session_queue(session_id)
        try:
            while line := await process.stdout.readline():
                try:
                    frame = json.loads(line)
                except ValueError:
                    session = self._sessions[session_id]
                    session.malformed_stdout_count += 1
                    prefix = repr(line[:80].decode(errors="replace"))
                    logger.warning(
                        "codex_stdout_non_json session=%s count=%d bytes=%d prefix=%s",
                        session_id,
                        session.malformed_stdout_count,
                        len(line),
                        prefix,
                    )
                    within_line_limit = len(line) <= 16 * 1024 * 1024
                    if within_line_limit and not session.malformed_stdout_reported:
                        session.malformed_stdout_reported = True
                        await queue.put(
                            _event(
                                "error",
                                session_id,
                                {
                                    "message": (
                                        "Codex app-server emitted malformed stdout"
                                    ),
                                    "count": session.malformed_stdout_count,
                                    "bytes": len(line),
                                    "prefix": prefix,
                                },
                            )
                        )
                    continue
                if isinstance(frame, dict):
                    await self._handle_frame(session_id, frame, queue)
        except ValueError as exc:
            await queue.put(
                _event(
                    "error",
                    session_id,
                    {
                        "message": "Codex output line exceeded the configured limit: "
                        f"{exc}"
                    },
                )
            )
            with contextlib.suppress(ProcessLookupError, OSError):
                self.process_group_signal(process.pid, signal.SIGTERM)
        finally:
            await self._finish_reader(session_id, process, queue)

    async def _handle_frame(
        self,
        session_id: str,
        frame: dict[str, Any],
        queue: asyncio.Queue[RunnerEvent | None],
    ) -> None:
        request_id = frame.get("id")
        request_key = (
            request_id
            if isinstance(request_id, (int, str)) and not isinstance(request_id, bool)
            else None
        )
        waiter = self._rpc_waiters.get(request_key) if request_key is not None else None
        if "method" not in frame and waiter and not waiter.done():
            if "error" in frame:
                raw_error = frame["error"]
                details = raw_error if isinstance(raw_error, dict) else {}
                message = str(details.get("message", raw_error))[:500]
                code = details.get("code")
                method_name = (
                    self._rpc_methods.get(request_key, "unknown")
                    if request_key is not None
                    else "unknown"
                )
                logger.error(
                    "codex_rpc_error session=%s method=%s request_id=%s error=%s",
                    session_id,
                    method_name,
                    request_id,
                    message,
                )
                if method_name.startswith("turn/"):
                    await queue.put(
                        _event(
                            "error",
                            session_id,
                            {"message": message, "code": code, "method": method_name},
                        )
                    )
                waiter.set_exception(RuntimeError(message))
            else:
                waiter.set_result(frame)
            return

        method = frame.get("method")
        params = frame.get("params")
        if method == "error" and isinstance(params, dict):
            error = params.get("error")
            error = error if isinstance(error, dict) else {}
            logger.error(
                "codex_error session=%s will_retry=%s thread=%s turn=%s message=%s",
                session_id,
                params.get("willRetry", False),
                params.get("threadId"),
                params.get("turnId"),
                str(error.get("message", "unknown Codex error"))[:500],
            )
        if method == "item/agentMessage/delta":
            session = self._sessions.get(session_id)
            if session is not None and session.first_text_ms is None:
                started_at = session.turn_started_at
                if started_at is not None:
                    session.first_text_ms = round(
                        (time.monotonic() - started_at) * 1000
                    )
        self._update_turn_state(session_id, method, params)
        resolved_request = self._resolved_request_id(method, params)
        for event in wire.parse_message(
            frame,
            session_id,
            self._sessions.get(session_id, _Session()).request_kinds,
            self._rpc_methods,
        ):
            self._remember_request(session_id, event, method, params)
            if event.kind == "session_end":
                self._sessions[session_id].status = (
                    "idle"
                    if event.payload.get("status") in {"completed", "interrupted"}
                    else "error"
                )
                self._log_terminal_observation(
                    session_id, method, params, event.payload
                )
            await queue.put(event)
        if resolved_request is not None:
            self._clear_request(session_id, resolved_request)

    def _update_turn_state(self, session_id: str, method: Any, params: Any) -> None:
        if method == "turn/started" and isinstance(params, dict):
            turn = params.get("turn")
            turn_id = turn.get("id") if isinstance(turn, dict) else None
            if isinstance(turn_id, str):
                session = self._sessions[session_id]
                session.turn_id = turn_id
                started = session.turn_started
                if started is not None and not started.done():
                    started.set_result(turn_id)
            session = self._sessions[session_id]
            session.status = "running"
            session.turn_started_at = time.monotonic()
        if method != "turn/completed":
            return
        session = self._sessions[session_id]
        raw_turn = params.get("turn") if isinstance(params, dict) else None
        turn = raw_turn if isinstance(raw_turn, dict) else params
        status = turn.get("status") if isinstance(turn, dict) else None
        session.status = "idle" if status in {"completed", "interrupted"} else "error"
        session.terminal_pending_approval = next(iter(session.pending), None)
        session.turn_id = None
        started = session.turn_started
        session.turn_started = None
        if started is not None and not started.done():
            started.set_result("")
        self._clear_turn_requests(session_id)

    def _log_terminal_observation(
        self, session_id: str, method: Any, params: Any, payload: dict[str, Any]
    ) -> None:
        session = self._sessions.get(session_id, _Session())
        raw_turn = params.get("turn") if isinstance(params, dict) else None
        turn = raw_turn if isinstance(raw_turn, dict) else {}
        error = turn.get("error")
        error_message = error.get("message") if isinstance(error, dict) else None
        logger.info(
            "codex_turn_observation request_id=%s turn_id=%s first_text_ms=%s "
            "terminal_method=%s terminal_status=%s error=%s pending_approval=%s "
            "session_status=%s",
            session.turn_start_request_id,
            turn.get("id"),
            session.first_text_ms,
            method,
            payload.get("status"),
            str(error_message)[:300] if error_message is not None else None,
            session.terminal_pending_approval,
            session.status,
        )
        session.turn_start_request_id = None
        session.turn_started_at = None
        session.first_text_ms = None
        session.terminal_pending_approval = None

    @staticmethod
    def _resolved_request_id(method: Any, params: Any) -> str | None:
        if method != "serverRequest/resolved" or not isinstance(params, dict):
            return None
        request_id = params.get("requestId")
        if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
            return None
        return str(request_id)

    def _remember_request(
        self, session_id: str, event: RunnerEvent, method: Any, params: Any
    ) -> None:
        if event.kind not in {"permission_requested", "wait_created"}:
            return
        request_id = event.payload.get("request_id")
        rpc_id = event.payload.get("rpc_id", request_id)
        if not isinstance(request_id, str):
            return
        session = self._sessions[session_id]
        session.pending.add(request_id)
        session.permission_inputs[request_id] = {
            "rpc_id": rpc_id,
            "method": method,
            "params": params if isinstance(params, dict) else {},
        }
        if isinstance(rpc_id, (str, int)) and not isinstance(rpc_id, bool):
            session.request_kinds[rpc_id] = (
                "question" if event.kind == "wait_created" else "permission"
            )

    async def _finish_reader(
        self,
        session_id: str,
        process: asyncio.subprocess.Process,
        queue: asyncio.Queue[RunnerEvent | None],
    ) -> None:
        await process.wait()
        if not self.process_group_exists(process.pid):
            process_state.clear_process_record(self.state_dir, session_id, process.pid)
        session = self._sessions.get(session_id)
        stderr_task = session.stderr_reader if session is not None else None
        if stderr_task is not None:
            await asyncio.gather(stderr_task, return_exceptions=True)
        if process.pid not in self._stopping_pids and self._session_status(
            session_id
        ) not in {"idle", "error"}:
            await queue.put(
                _event(
                    "error",
                    session_id,
                    {
                        "message": "Codex process exited unexpectedly",
                        "returncode": process.returncode,
                        "stderr": list(
                            self._sessions.get(session_id, _Session()).stderr or ()
                        ),
                    },
                )
            )
            await queue.put(
                _event(
                    "session_end",
                    session_id,
                    {"status": "failed", "terminal": True},
                )
            )
            self._sessions[session_id].status = "error"
        for request_id, request_session in tuple(self._rpc_sessions.items()):
            if request_session != session_id:
                continue
            waiter = self._rpc_waiters.get(request_id)
            if waiter is not None and not waiter.done():
                waiter.set_exception(
                    RuntimeError("Codex process exited before its response")
                )
        if session_id not in self._restarting:
            await queue.put(None)
        self._retire_process(session_id, process)

    async def send(self, ref: SessionRef, prompt: str) -> None:
        session_id = ref.session_id
        session = self._sessions.get(session_id)
        thread = session.thread_id if session is not None else None
        if session is None or not thread:
            raise RuntimeError("Codex thread is unavailable")
        if self._session_status(session_id) == "running":
            turn = session.turn_id if session is not None else None
            if turn is None:
                started = session.turn_started if session is not None else None
                if started is None:
                    raise RuntimeError("Codex turn is starting without a turn identity")
                turn = await asyncio.wait_for(asyncio.shield(started), 10)
                if not turn:
                    raise RuntimeError("Codex turn started without a turn id")
            raw = wire.encode_turn_steer(thread, turn, prompt, self._id())
            try:
                await self._rpc(ref, raw, "turn/steer")
            except BaseException:
                session = self._sessions.get(session_id)
                if session is not None:
                    process = session.process
                    session.status = (
                        "error"
                        if process is None or process.returncode is not None
                        else "idle"
                    )
                    session.turn_id = None
                raise
            return

        await self._start_turn(ref, session, thread, prompt)

    async def _start_turn(
        self, ref: SessionRef, session: _Session, thread: str, prompt: str
    ) -> None:
        session_id = ref.session_id
        loop = asyncio.get_running_loop()
        started = loop.create_future()
        session.turn_started = started
        session.turn_id = None
        session.status = "running"
        request_id = self._id()
        session.turn_start_request_id = request_id
        session.turn_started_at = time.monotonic()
        session.first_text_ms = None
        try:
            raw = wire.encode_turn_start(
                thread,
                prompt,
                request_id,
                session.spec.reasoning_effort if session.spec is not None else None,
            )
            await self._rpc(ref, raw, "turn/start")
            try:
                await asyncio.wait_for(
                    asyncio.shield(started), self._TURN_STARTED_TIMEOUT
                )
            except TimeoutError:
                message = "Codex turn/started notification timed out"
                logger.warning(
                    "turn_start_wait_timeout session=%s request_id=%s",
                    session_id,
                    request_id,
                )
                await self._session_queue(session_id).put(
                    _event(
                        "error",
                        session_id,
                        {"message": message, "request_id": request_id},
                    )
                )
                raise TimeoutError(message) from None
        except BaseException:
            current = self._sessions.get(session_id)
            if current is not None:
                process = current.process
                current.status = (
                    "error"
                    if process is None or process.returncode is not None
                    else "idle"
                )
                current.turn_id = None
                current.turn_started = None
                current.turn_start_request_id = None
                current.turn_started_at = None
            if not started.done():
                started.set_result("")
            raise
        finally:
            current = self._sessions.get(session_id)
            if current is not None and current.turn_started is started:
                current.turn_started = None

    def _live_process(self, ref: SessionRef) -> asyncio.subprocess.Process:
        session = self._sessions.get(ref.session_id)
        process = session.process if session is not None else None
        if process is None or process.returncode is not None:
            raise RuntimeError("Codex process is not running")
        return process

    async def idle_status(self, ref: SessionRef) -> str:
        return self._session_status(ref.session_id) or "unknown"

    def process_alive(self, ref: SessionRef) -> bool:
        session = self._sessions.get(ref.session_id)
        process = session.process if session is not None else None
        return process is not None and process.returncode is None

    async def events(self, ref: SessionRef) -> AsyncGenerator[RunnerEvent]:
        session = self._sessions.setdefault(ref.session_id, _Session())
        if session.queue is None:
            session.queue = asyncio.Queue()
        queue = session.queue
        while True:
            event = await queue.get()
            if event is None:
                return
            yield event

    async def respond_permission(
        self, ref: SessionRef, request_id: str, decision: str
    ) -> None:
        session_id = ref.session_id
        session = self._sessions.get(session_id)
        if session is not None and request_id in session.answered:
            return
        info = (
            session.permission_inputs.get(request_id) if session is not None else None
        )
        rpc = info.get("rpc_id") if info else None
        stale = session is None or request_id not in session.pending
        if not info or not isinstance(rpc, (str, int)) or isinstance(rpc, bool):
            await self._session_queue(session_id).put(
                _event(
                    "error",
                    session_id,
                    {
                        "message": "stale or unknown Codex request denied",
                        "request_id": request_id,
                    },
                )
            )
            return
        method = info.get("method")
        params = info.get("params", {})
        permissions = params.get("permissions") if isinstance(params, dict) else None
        if stale:
            await self._deny_request(ref, session_id, request_id, method, rpc)
            return
        if method == "item/tool/requestUserInput":
            answered = self._sessions[session_id].answered
            answered.add(request_id)
            try:
                await self._write(
                    ref,
                    wire.encode_error_response(
                        rpc, -32601, "Codex question responses are unsupported"
                    ),
                )
            except BaseException:
                answered.discard(request_id)
                raise
            await self._session_queue(session_id).put(
                _event(
                    "error",
                    session_id,
                    {
                        "message": "Codex question response is unsupported; denied",
                        "request_id": request_id,
                    },
                )
            )
            return
        raw = wire.encode_server_response(
            str(method),
            rpc,
            decision.casefold() in {"allow", "approve", "approved"},
            permissions=permissions if isinstance(permissions, dict) else None,
        )
        answered = self._sessions[session_id].answered
        answered.add(request_id)
        try:
            await self._write(ref, raw)
        except BaseException:
            answered.discard(request_id)
            raise

    async def _deny_request(
        self,
        ref: SessionRef,
        session_id: str,
        request_id: str,
        method: Any,
        rpc_id: str | int,
    ) -> None:
        response = (
            wire.encode_error_response(rpc_id, -32600, "Stale Codex request denied")
            if method == "item/tool/requestUserInput"
            else wire.encode_server_response(str(method), rpc_id, False)
        )
        answered = self._sessions[session_id].answered
        answered.add(request_id)
        try:
            await self._write(ref, response)
        except BaseException:
            answered.discard(request_id)
            raise
        await self._session_queue(session_id).put(
            _event(
                "error",
                session_id,
                {"message": "stale Codex request denied", "request_id": request_id},
            )
        )

    async def interrupt(self, ref: SessionRef) -> None:
        session_id = ref.session_id
        if self._session_status(session_id) != "running":
            return
        session = self._sessions.get(session_id)
        thread = session.thread_id if session is not None else None
        turn = session.turn_id if session is not None else None
        if not thread or not turn:
            raise TimeoutError(
                "failed_interrupt: turn identity unavailable; interrupt was not sent"
            )
        await self._rpc(
            ref,
            wire.encode_turn_interrupt(thread, turn, self._id()),
            "turn/interrupt",
        )
        try:
            await asyncio.wait_for(
                self._wait_turn_end(session_id), self.interrupt_timeout
            )
        except TimeoutError as exc:
            raise TimeoutError("failed_interrupt: turn completion timed out") from exc
        if self._session_status(session_id) != "idle":
            raise TimeoutError("failed_interrupt: Codex turn did not complete cleanly")

    async def _wait_turn_end(self, session_id: str) -> None:
        while self._session_status(session_id) == "running":
            await asyncio.sleep(0.02)

    def _clear_request(self, session_id: str, request_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.pending.discard(request_id)
        session.permission_inputs.pop(request_id, None)
        session.answered.discard(request_id)

    def _clear_turn_requests(self, session_id: str) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.pending.clear()
        session.permission_inputs.clear()
        session.answered.clear()
        session.request_kinds.clear()

    def validate_resume_mode(self, mode: str) -> None:
        if mode not in wire.MODE_MAP:
            raise ValueError(f"unsupported runner mode: {mode}")

    async def resume(
        self, ref: SessionRef, settings: ResumeSettings | None = None
    ) -> SessionRef:
        spec = self._load_spec(ref)
        thread_id = self._load_thread_id(ref.session_id)
        if thread_id is None:
            raise RuntimeError("persisted Codex thread id is unavailable")
        if self._is_unavailable(ref.session_id):
            raise RuntimeError(f"Codex session {ref.session_id} is unavailable")
        if settings is not None and settings.mode_id is not None:
            self.validate_resume_mode(settings.mode_id)
            spec = replace(spec, mode_id=settings.mode_id)
            self._persist_spec(ref.session_id, spec)
        session = self._sessions.get(ref.session_id)
        queue = session.queue if session is not None else None
        process = session.process if session is not None else None
        if process is None and not await self._recover_orphan(ref.session_id):
            raise RuntimeError(
                "persisted Codex process for "
                f"{ref.session_id} is unavailable or mismatched"
            )
        self._restarting.add(ref.session_id)
        try:
            if process is not None:
                await self.stop(ref)
            self._initialize_session(ref.session_id)
            self._sessions[ref.session_id].spec = spec
            if queue is not None:
                self._sessions[ref.session_id].queue = queue
            await self._spawn(ref, resume_id=thread_id)
        except BaseException as exc:
            with contextlib.suppress(Exception):
                await self.stop(ref)
            await self._session_queue(ref.session_id).put(
                _event(
                    "error", ref.session_id, {"message": f"Codex resume failed: {exc}"}
                )
            )
            await self._session_queue(ref.session_id).put(None)
            self._clear_live_state(ref.session_id)
            raise
        finally:
            self._restarting.discard(ref.session_id)
        return ref

    async def usage(self, ref: SessionRef) -> dict[str, Any]:
        response = await self._rpc(
            ref, wire.encode_rate_limits_read(self._id()), "account/rateLimits/read"
        )
        result = response.get("result")
        if not isinstance(result, dict):
            return {"limit": "unknown", "source": "codex"}
        response_id = response.get("id")
        if not isinstance(response_id, (str, int)) or isinstance(response_id, bool):
            return {"limit": "unknown", "source": "codex"}
        events = wire.parse_message(
            {"id": response_id, "result": result},
            ref.session_id,
            self._sessions.get(ref.session_id, _Session()).request_kinds,
            {response_id: "account/rateLimits/read"},
        )
        for event in events:
            if event.kind == "usage":
                return event.payload
        return {"limit": "unknown", "source": "codex"}

    def _persist_thread_id(self, session_id: str, thread_id: str) -> None:
        path = self._spec_path(session_id)
        value = json.loads(path.read_text(encoding="utf-8"))
        value["thread_id"] = thread_id
        self._write_state(path, value)

    def _load_thread_id(self, session_id: str) -> str | None:
        try:
            value = json.loads(self._spec_path(session_id).read_text(encoding="utf-8"))
        except OSError, ValueError, TypeError:
            return None
        thread_id = value.get("thread_id") if isinstance(value, dict) else None
        return thread_id if isinstance(thread_id, str) else None

    def _persist_process(
        self,
        session_id: str,
        pid: int,
        command: list[str],
        identity: ProcessIdentity,
    ) -> None:
        path = self._spec_path(session_id)
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(
            pid=pid,
            process_group=pid,
            command=command,
            started_at=identity.start_time,
            session_id=session_id,
        )
        value.pop("recovery_status", None)
        value.pop("recovery_reason", None)
        self._write_state(path, value)

    async def _recover_orphan(self, session_id: str) -> bool:
        return await process_state.stop_orphan(
            session_id,
            path=self._spec_path(session_id),
            product="Codex",
            inspect=self.process_inspector,
            signal_group=self.process_group_signal,
            group_exists=self.process_group_exists,
            timeout=self.stop_timeout,
            mark_unavailable=lambda sid, value, reason: process_state.mark_unavailable(
                self.state_dir, sid, value, reason, "Codex"
            ),
            clear_record=lambda sid, pid: process_state.clear_process_record(
                self.state_dir, sid, pid
            ),
        )

    async def _wait_for_group_exit(self, process_group: int, timeout: float) -> bool:
        return await process_state.wait_for_group_exit(
            process_group, timeout, self.process_group_exists
        )

    def _is_unavailable(self, session_id: str) -> bool:
        try:
            value = json.loads(self._spec_path(session_id).read_text(encoding="utf-8"))
        except OSError, ValueError, TypeError:
            return False
        return isinstance(value, dict) and value.get("recovery_status") == "unavailable"

    @staticmethod
    def _write_state(path: Path, value: dict[str, Any]) -> None:
        process_state.write_state(path, value)

    async def recover_orphans(self) -> set[str]:
        """Sweep persisted Codex processes before the supervisor resumes sessions."""
        unavailable: set[str] = set()
        if not self.state_dir.exists():
            return unavailable
        for path in self.state_dir.glob("*.json"):
            try:
                session_id = str(uuid.UUID(path.stem))
                value = json.loads(path.read_text(encoding="utf-8"))
            except OSError, ValueError, TypeError:
                continue
            if not isinstance(value, dict):
                continue
            if value.get("recovery_status") == "unavailable":
                unavailable.add(session_id)
                continue
            if any(
                key in value for key in ("pid", "process_group", "command")
            ) and not await self._recover_orphan(session_id):
                unavailable.add(session_id)
        return unavailable

    async def stop(self, ref: SessionRef) -> None:
        session = self._sessions.get(ref.session_id)
        process = session.process if session is not None else None
        if process is None:
            return
        reader = session.reader if session is not None else None
        stderr_reader = session.stderr_reader if session is not None else None
        self._stopping_pids.add(process.pid)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        if not await self._wait_for_group_exit(process.pid, self.stop_timeout):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            if not await self._wait_for_group_exit(process.pid, self.stop_timeout):
                raise RuntimeError("Codex process group did not exit")
        if process.returncode is None:
            await process.wait()
        await self._join_task(reader)
        await self._join_task(stderr_reader)
        process_state.clear_process_record(self.state_dir, ref.session_id, process.pid)
        self._retire_process(ref.session_id, process)

    async def _join_task(self, task: asyncio.Task[None] | None) -> None:
        if task is None:
            return
        if not task.done():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
            except TimeoutError:
                task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    def _retire_process(
        self, session_id: str, process: asyncio.subprocess.Process
    ) -> None:
        session = self._sessions.get(session_id)
        if session is None or session.process is not process:
            return
        session.process = None
        session.reader = None
        session.stderr_reader = None
        session.pending.clear()
        session.permission_inputs.clear()
        session.answered.clear()
        session.stderr = None
        session.request_kinds.clear()
        session.thread_id = None
        session.turn_id = None
        session.turn_started = None
        for request_id, request_session in tuple(self._rpc_sessions.items()):
            if request_session == session_id:
                self._rpc_sessions.pop(request_id, None)
                self._rpc_methods.pop(request_id, None)
        self._stopping_pids.discard(process.pid)

    def _clear_live_state(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
        for request_id, request_session in tuple(self._rpc_sessions.items()):
            if request_session == session_id:
                self._rpc_sessions.pop(request_id, None)
                self._rpc_methods.pop(request_id, None)
                self._rpc_waiters.pop(request_id, None)

    async def close(self) -> None:
        refs = [
            SessionRef(spec.provider, session_id)
            for session_id, session in self._sessions.items()
            if session.process is not None
            if (spec := session.spec) is not None
        ]
        await asyncio.gather(*(self.stop(ref) for ref in refs))


def _event(kind: EventKind, session_id: str, payload: dict[str, Any]) -> RunnerEvent:
    return RunnerEvent(
        kind=kind,
        session_id=session_id,
        payload=payload,
        provider_id="codex-app-server",
    )

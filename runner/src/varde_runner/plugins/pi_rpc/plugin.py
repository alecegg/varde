"""Pi RPC subprocess adapter."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import uuid
from collections import deque
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from varde_runner.config import Model, adapter_state_root
from varde_runner.events import RunnerEvent
from varde_runner.plugins import (
    RunnerCapabilities,
    SessionRef,
    SessionSettings,
    SessionSpec,
    child_environment,
)
from varde_runner.plugins.pi_rpc import wire
from varde_runner.plugins.process_state import (
    inspect_process_async,
    process_group_exists,
    wait_for_group_exit,
)
from varde_runner.protocol import ResumeSettings, UnsupportedCapability

logger = logging.getLogger(__name__)


class PiRpcPlugin:
    config_table = "pi_rpc"
    _STARTUP_OUTPUT_TIMEOUT = 60.0
    _STDERR_TAIL_BYTES = 8 * 1024
    capabilities = RunnerCapabilities(
        resume=True,
        permission_commands=False,
        usage=True,
        idle_status=True,
        persistent_process=True,
        steer=True,
        interrupt=True,
        respond=False,
    )

    def __init__(
        self,
        executable: str | Path | None = None,
        *,
        state_dir: str | Path | None = None,
    ) -> None:
        self.executable = str(executable) if executable else shutil.which("pi")
        self.state_dir = (
            Path(state_dir) if state_dir else adapter_state_root() / "pi-rpc"
        )
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._queues: dict[str, asyncio.Queue[RunnerEvent | None]] = {}
        self._readers: dict[str, asyncio.Task[None]] = {}
        self._stderr_readers: dict[str, asyncio.Task[None]] = {}
        self._pending: dict[str, dict[str, asyncio.Future[dict[str, Any]]]] = {}
        self._commands: dict[str, dict[str, str]] = {}
        self._specs: dict[str, SessionSpec] = {}
        self._session_files: dict[str, str] = {}
        self._settled: dict[str, asyncio.Event] = {}
        self._running: dict[str, bool] = {}
        self._counter = 0
        self._stderr_tails: dict[str, bytearray] = {}
        self._prompt_activity: dict[str, asyncio.Event] = {}
        self._prompts: dict[str, deque[str]] = {}
        self._stopping: set[str] = set()
        self._failure_reported: set[str] = set()

    def session_settings(self, model: Model) -> SessionSettings:
        return SessionSettings(model.model, model.reasoning_effort, model.mode)

    async def start(self, spec: SessionSpec) -> SessionRef:
        if not self.executable:
            raise RuntimeError("pi executable not found on PATH")
        if spec.mode_id not in {None, "read-only"}:
            raise RuntimeError(
                "pi-rpc supports read-only mode only because it has no approval flow"
            )
        session_id = str(uuid.uuid4())
        ref = SessionRef(spec.provider, session_id)
        self._specs[session_id] = spec
        self._initialize(session_id)
        self._save_spec(session_id, spec)
        try:
            await self._spawn(ref)
            await self.usage(ref)
            if spec.prompt:
                await self.send(ref, spec.prompt)
        except BaseException:
            with contextlib.suppress(Exception):
                await self.stop(ref)
            with contextlib.suppress(OSError):
                self._path(session_id).unlink()
            raise
        return ref

    def _path(self, session_id: str) -> Path:
        return self.state_dir / f"{uuid.UUID(session_id)}.json"

    def _save_spec(self, session_id: str, spec: SessionSpec) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self._path(session_id)
        self._write_state(
            path,
            {
                "provider": spec.provider,
                "model": spec.model,
                "workspace_id": spec.workspace_id,
                "cwd": spec.cwd,
                "reasoning_effort": spec.reasoning_effort,
                "mode_id": spec.mode_id,
                "agent_id": spec.agent_id,
                "runner_harness": spec.runner_harness,
            },
        )

    @staticmethod
    def _write_state(path: Path, state: dict[str, Any]) -> None:
        temp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(state, stream)
            os.replace(temp_path, path)
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

    def _initialize(self, session_id: str) -> None:
        self._stopping.discard(session_id)
        self._failure_reported.discard(session_id)
        self._queues[session_id] = asyncio.Queue()
        self._pending[session_id] = {}
        self._commands[session_id] = {}
        self._settled[session_id] = asyncio.Event()
        self._settled[session_id].set()
        self._running[session_id] = False
        self._stderr_tails[session_id] = bytearray()
        self._prompt_activity[session_id] = asyncio.Event()
        self._prompts[session_id] = deque(maxlen=8)

    async def _spawn(self, ref: SessionRef) -> None:
        spec = self._specs[ref.session_id]
        command = wire.build_command(
            spec.model,
            ref.session_id,
            self._session_files.get(ref.session_id),
            spec.reasoning_effort,
            spec.mode_id or "read-only",
        )
        command[0] = self.executable or command[0]
        logger.info("pi_rpc_start session=%s command=%s", ref.session_id, command)
        env = child_environment()
        env.update(
            {
                "VARDE_AGENT_ID": spec.agent_id or spec.workspace_id,
                "VARDE_HARNESS": "pi-rpc",
            }
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=spec.cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=16 * 1024 * 1024,
        )
        self._processes[ref.session_id] = process
        state = json.loads(self._path(ref.session_id).read_text(encoding="utf-8"))
        state.update(pid=process.pid, process_group=process.pid, command=command)
        try:
            identity = await self._process_identity(process.pid)
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            await process.wait()
            raise
        if identity is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            await process.wait()
            raise RuntimeError("Pi process identity could not be inspected")
        state["started_at"] = identity[0]
        self._write_state(self._path(ref.session_id), state)
        self._readers[ref.session_id] = asyncio.create_task(self._read(ref, process))
        self._stderr_readers[ref.session_id] = asyncio.create_task(
            self._drain_stderr(ref.session_id, process)
        )

    async def _drain_stderr(
        self, sid: str, process: asyncio.subprocess.Process
    ) -> None:
        if process.stderr:
            while line := await process.stderr.readline():
                for prompt in self._prompts[sid]:
                    if prompt:
                        line = line.replace(prompt.encode(), b"[prompt]")
                line = bytes(
                    byte if byte in (9, 10, 13) or 32 <= byte < 127 else 63
                    for byte in line
                )
                tail = self._stderr_tails[sid]
                tail.extend(line)
                if len(tail) > self._STDERR_TAIL_BYTES:
                    del tail[: -self._STDERR_TAIL_BYTES]

    async def _report_stdout_closed(self, sid: str) -> None:
        if sid in self._stopping or sid in self._failure_reported:
            return
        self._failure_reported.add(sid)
        self._prompt_activity[sid].set()
        detail = (
            bytes(self._stderr_tails[sid]).decode("ascii", errors="replace").strip()
        )
        message = "Pi RPC stdout closed unexpectedly"
        if detail:
            message += f": {detail}"
        await self._queues[sid].put(
            RunnerEvent("error", sid, {"message": message[:2048]}, "pi-rpc")
        )
        await self._queues[sid].put(
            RunnerEvent("status", sid, {"status": "error", "terminal": True}, "pi-rpc")
        )
        self._running[sid] = False
        self._settled[sid].set()

    async def _read(  # noqa: C901, PLR0912, PLR0915 - dispatches protocol frames.
        self, ref: SessionRef, process: asyncio.subprocess.Process
    ) -> None:
        if process.stdout is None:
            raise RuntimeError("Pi RPC stdout is unavailable")
        sid = ref.session_id
        started_at = asyncio.get_running_loop().time()
        first_stdout = True
        frame_types: list[str] = []
        try:
            while line := await process.stdout.readline():
                if not line.endswith(b"\n"):
                    await self._queues[sid].put(
                        RunnerEvent(
                            "error",
                            sid,
                            {"message": "Pi RPC frame missing LF terminator"},
                            "pi-rpc",
                        )
                    )
                    break
                frame = line[:-1].removesuffix(b"\r")
                try:
                    frame_record = json.loads(frame)
                    frame_type = (
                        frame_record.get("type", "unknown")
                        if isinstance(frame_record, dict)
                        else "non_object"
                    )
                except UnicodeDecodeError, ValueError, RecursionError:
                    frame_type = "malformed"
                if first_stdout:
                    first_stdout = False
                    elapsed_ms = round(
                        (asyncio.get_running_loop().time() - started_at) * 1000
                    )
                    logger.info(
                        "pi_rpc_first_stdout_frame session=%s elapsed_ms=%d type=%s",
                        sid,
                        elapsed_ms,
                        frame_type,
                    )
                if len(frame_types) < 12:
                    frame_types.append(str(frame_type))
                    logger.info(
                        "pi_rpc_initial_frame session=%s index=%d type=%s",
                        sid,
                        len(frame_types),
                        frame_type,
                    )
                events, response = wire.parse_frame(frame, sid, self._commands[sid])
                if response is None:
                    self._prompt_activity[sid].set()
                for event in events:
                    if event.kind == "status":
                        running = event.payload.get("status") == "running"
                        self._running[sid] = running
                        if running:
                            self._settled[sid].clear()
                        else:
                            self._settled[sid].set()
                    if (
                        event.kind == "status"
                        and event.payload.get("status") == "error"
                    ):
                        self._running[sid] = False
                        self._settled[sid].set()
                    await self._queues[sid].put(event)
                if response and "extension_ui_cancel" in response:
                    await self._write(
                        ref,
                        wire.encode_extension_ui_cancel(
                            response["extension_ui_cancel"]
                        ),
                    )
                elif response and "id" in response:
                    command_id = response.get("id")
                    waiter = (
                        self._pending[sid].get(command_id)
                        if isinstance(command_id, str)
                        else None
                    )
                    if waiter and not waiter.done():
                        if response.get("success") is False:
                            raw_error = response.get("error")
                            detail = (
                                raw_error.get("message")
                                if isinstance(raw_error, dict)
                                else raw_error
                            )
                            message = str(detail or "Pi RPC command failed")[:2048]
                            await self._queues[sid].put(
                                RunnerEvent(
                                    "error", sid, {"message": message}, "pi-rpc"
                                )
                            )
                            await self._queues[sid].put(
                                RunnerEvent(
                                    "status", sid, {"status": "error"}, "pi-rpc"
                                )
                            )
                            if (
                                command_id
                                and self._commands[sid].get(command_id) == "prompt"
                            ):
                                self._running[sid] = False
                                self._settled[sid].set()
                        waiter.set_result(response)
                    if response.get("command") == "get_session_stats" and response.get(
                        "success"
                    ):
                        data = response.get("data")
                        if isinstance(data, dict) and isinstance(
                            data.get("sessionFile"), str
                        ):
                            self._session_files[sid] = data["sessionFile"]
                            self._save_session_file(sid, data["sessionFile"])
                if (
                    response
                    and response.get("command") == "prompt"
                    and response.get("success")
                ):
                    data = response.get("data")
                    disposition = (
                        data.get("disposition") if isinstance(data, dict) else "unknown"
                    )
                    logger.info(
                        "pi_prompt_response session=%s disposition=%s", sid, disposition
                    )
                if (
                    response
                    and response.get("command") == "prompt"
                    and response.get("success")
                ):
                    data = response.get("data")
                    if isinstance(data, dict) and data.get("disposition") == "handled":
                        self._settled[sid].set()
            else:
                await self._report_stdout_closed(sid)
            await process.wait()
        except asyncio.CancelledError:
            raise
        except BrokenPipeError, ConnectionError:
            await self._report_stdout_closed(sid)
        except ValueError as exc:
            await self._queues[sid].put(
                RunnerEvent(
                    "error",
                    sid,
                    {"message": f"Pi RPC frame exceeded the reader limit: {exc}"},
                    "pi-rpc",
                )
            )
        finally:
            if (
                process.returncode is not None
                and sid not in self._stopping
                and sid not in self._failure_reported
            ):
                self._failure_reported.add(sid)
                self._prompt_activity[sid].set()
                detail = (
                    bytes(self._stderr_tails[sid])
                    .decode("ascii", errors="replace")
                    .strip()
                )
                message = ("Pi process exited" + (f": {detail}" if detail else ""))[
                    :2048
                ]
                await self._queues[sid].put(
                    RunnerEvent("error", sid, {"message": message}, "pi-rpc")
                )
                await self._queues[sid].put(
                    RunnerEvent(
                        "status",
                        sid,
                        {"status": "error", "terminal": True},
                        "pi-rpc",
                    )
                )
                self._running[sid] = False
                self._settled[sid].set()
            if self._running.get(sid):
                self._running[sid] = False
                self._settled[sid].set()
            for waiter in self._pending[sid].values():
                if not waiter.done():
                    waiter.set_exception(RuntimeError("Pi RPC process disconnected"))
            await self._queues[sid].put(None)

    def _id(self) -> str:
        self._counter += 1
        return f"varde-{self._counter}"

    def _save_session_file(self, session_id: str, session_file: str) -> None:
        path = self._path(session_id)
        state = json.loads(path.read_text(encoding="utf-8"))
        state["session_file"] = session_file
        self._write_state(path, state)

    @staticmethod
    async def _process_identity(pid: int) -> tuple[str, str] | None:
        identity = await inspect_process_async(pid, "Pi")
        return (identity.start_time, identity.command) if identity else None

    async def _write(self, ref: SessionRef, record: str) -> None:
        process = self._live(ref)
        if process.stdin is None:
            raise RuntimeError("Pi RPC stdin is unavailable")
        process.stdin.write((record + "\n").encode("utf-8"))
        await process.stdin.drain()

    async def _command(
        self, ref: SessionRef, command: str, **fields: Any
    ) -> dict[str, Any]:
        request_id = self._id()
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[ref.session_id][request_id] = future
        self._commands[ref.session_id][request_id] = command
        try:
            await self._write(ref, wire.encode_command(command, request_id, **fields))
            result = await asyncio.wait_for(future, timeout=30)
        finally:
            self._pending[ref.session_id].pop(request_id, None)
            self._commands[ref.session_id].pop(request_id, None)
        if result.get("success") is not True:
            raise RuntimeError(
                f"Pi RPC {command} failed: {result.get('error', 'unknown error')}"
            )
        return result

    async def send(self, ref: SessionRef, prompt: str) -> None:
        if self._running.get(ref.session_id):
            await self.steer(ref, prompt)
            return
        self._settled[ref.session_id].clear()
        self._prompt_activity[ref.session_id].clear()
        self._prompts[ref.session_id].append(prompt)
        result = await self._command(ref, "prompt", message=prompt)
        data = result.get("data")
        if isinstance(data, dict) and data.get("disposition") == "handled":
            self._settled[ref.session_id].set()
        else:
            try:
                await asyncio.wait_for(
                    self._prompt_activity[ref.session_id].wait(),
                    timeout=self._STARTUP_OUTPUT_TIMEOUT,
                )
            except TimeoutError:
                tail = (
                    bytes(self._stderr_tails[ref.session_id])
                    .decode("ascii", errors="replace")
                    .strip()
                )
                message = "Pi produced no session output after accepting the prompt"
                if tail:
                    message += f": {tail}"
                await self._queues[ref.session_id].put(
                    RunnerEvent(
                        "error", ref.session_id, {"message": message[:2048]}, "pi-rpc"
                    )
                )
                await self._queues[ref.session_id].put(
                    RunnerEvent("status", ref.session_id, {"status": "error"}, "pi-rpc")
                )
                self._settled[ref.session_id].set()
            await asyncio.wait_for(self._settled[ref.session_id].wait(), timeout=3600)
        self._live(ref)

    async def steer(self, ref: SessionRef, prompt: str) -> None:
        await self._command(ref, "steer", message=prompt)

    async def interrupt(self, ref: SessionRef) -> None:
        await self._command(ref, "abort")
        await asyncio.wait_for(self._settled[ref.session_id].wait(), timeout=10)

    async def idle_status(self, ref: SessionRef) -> str:
        return "running" if self._running.get(ref.session_id) else "idle"

    async def events(self, ref: SessionRef) -> AsyncGenerator[RunnerEvent]:
        queue = self._queues[ref.session_id]
        while (event := await queue.get()) is not None:
            yield event

    async def usage(self, ref: SessionRef) -> dict[str, Any]:
        try:
            result = await self._command(ref, "get_session_stats")
            data = result.get("data")
            tokens = data.get("tokens") if isinstance(data, dict) else None
            if not isinstance(tokens, dict):
                return {"source": "pi", "usage": "unknown"}
            return {
                "source": "pi",
                "input_tokens": tokens.get("input"),
                "output_tokens": tokens.get("output"),
                "cache_read_tokens": tokens.get("cacheRead"),
                "cache_write_tokens": tokens.get("cacheWrite"),
                "total_tokens": tokens.get("total"),
                "cost": data.get("cost") if isinstance(data, dict) else None,
            }
        except RuntimeError, TimeoutError, KeyError:
            return {"source": "pi", "usage": "unknown"}

    def validate_resume_mode(self, mode: str) -> None:
        if mode != "read-only":
            raise UnsupportedCapability(
                "pi-rpc supports read-only mode only because it has no approval flow"
            )

    async def resume(
        self, ref: SessionRef, settings: ResumeSettings | None = None
    ) -> SessionRef:
        if settings is not None and settings.mode_id is not None:
            self.validate_resume_mode(settings.mode_id)
        try:
            state = json.loads(self._path(ref.session_id).read_text(encoding="utf-8"))
            if isinstance(state.get("session_file"), str):
                self._session_files[ref.session_id] = state["session_file"]
            spec = SessionSpec(
                **{
                    key: state[key]
                    for key in SessionSpec.__dataclass_fields__
                    if key in state
                }
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RuntimeError("Pi session metadata is unavailable") from exc
        self._specs[ref.session_id] = spec
        self._initialize(ref.session_id)
        await self._spawn(ref)
        return ref

    async def recover_orphans(self) -> set[str]:
        unavailable: set[str] = set()
        if not self.state_dir.exists():
            return unavailable
        for path in self.state_dir.glob("*.json"):
            try:
                session_id = str(uuid.UUID(path.stem))
                state = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(state, dict):
                    continue
                if state.get("recovery_status") == "unavailable":
                    unavailable.add(session_id)
                    continue
                pid, group = state.get("pid"), state.get("process_group")
                if (
                    not isinstance(pid, int)
                    or isinstance(pid, bool)
                    or not isinstance(group, int)
                    or isinstance(group, bool)
                ):
                    continue
                identity = await self._process_identity(pid)
                if identity is None:
                    state.pop("pid", None)
                    state.pop("process_group", None)
                    state.pop("command", None)
                    self._write_state(path, state)
                    continue
                start_time, command_text = identity
                if start_time != state.get("started_at") or not all(
                    arg in command_text for arg in state.get("command", [])
                ):
                    state["recovery_status"] = "unavailable"
                    self._write_state(path, state)
                    unavailable.add(session_id)
                    continue
                try:
                    os.killpg(group, signal.SIGTERM)
                except ProcessLookupError:
                    for key in ("pid", "process_group", "command", "started_at"):
                        state.pop(key, None)
                    self._write_state(path, state)
                    continue
                if not await wait_for_group_exit(group, 2, self._group_exists):
                    os.killpg(group, signal.SIGKILL)
                    if not await wait_for_group_exit(group, 2, self._group_exists):
                        state["recovery_status"] = "unavailable"
                        self._write_state(path, state)
                        unavailable.add(session_id)
                        continue
                for key in ("pid", "process_group", "command", "started_at"):
                    state.pop(key, None)
                self._write_state(path, state)
            except OSError, ValueError, TypeError, subprocess.SubprocessError:
                unavailable.add(path.stem)
        return unavailable

    def _live(self, ref: SessionRef) -> asyncio.subprocess.Process:
        process = self._processes.get(ref.session_id)
        if process is None or process.returncode is not None:
            raise RuntimeError("Pi RPC process is not running")
        return process

    @staticmethod
    def _group_exists(group: int) -> bool:
        return process_group_exists(group)

    async def stop(self, ref: SessionRef) -> None:
        process = self._processes.get(ref.session_id)
        if process is None:
            return
        self._stopping.add(ref.session_id)
        if process.stdin:
            process.stdin.close()
            with contextlib.suppress(BrokenPipeError, ConnectionError):
                await process.stdin.wait_closed()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), 2)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
        for tasks in (self._readers, self._stderr_readers):
            task = tasks.pop(ref.session_id, None)
            if task:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.wait_for(task, 2)
        self._processes.pop(ref.session_id, None)
        state_path = self._path(ref.session_id)
        with contextlib.suppress(OSError, ValueError):
            state = json.loads(state_path.read_text(encoding="utf-8"))
            for key in ("pid", "process_group", "command"):
                state.pop(key, None)
            self._write_state(state_path, state)
        self._queues.pop(ref.session_id, None)
        self._pending.pop(ref.session_id, None)
        self._commands.pop(ref.session_id, None)
        for sessions in (
            self._settled,
            self._running,
            self._stderr_tails,
            self._prompt_activity,
            self._prompts,
            self._specs,
            self._session_files,
        ):
            sessions.pop(ref.session_id, None)
        self._failure_reported.discard(ref.session_id)
        self._stopping.discard(ref.session_id)

    async def close(self) -> None:
        await asyncio.gather(
            *(
                self.stop(SessionRef(self._specs[sid].provider, sid))
                for sid in list(self._processes)
            )
        )

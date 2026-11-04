"""Claude Code CLI adapter using its stream-json interface."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import uuid
from collections import deque
from collections.abc import AsyncGenerator, Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from varde_runner.bot_profile import (
    check_restricted_overlay,
    is_restricted,
    restricted_environment,
    restricted_profile,
)
from varde_runner.config import Model, adapter_state_root
from varde_runner.events import EventKind, RunnerEvent
from varde_runner.plugins import (
    RunnerCapabilities,
    SessionRef,
    SessionSettings,
    SessionSpec,
    child_environment,
    process_state,
)
from varde_runner.plugins.claude_cli import wire
from varde_runner.protocol import ResumeSettings

REMOVED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
)


ProcessIdentity = process_state.ProcessIdentity


def child_env(spec: SessionSpec, extra: dict[str, str] | None = None) -> dict[str, str]:
    if is_restricted(spec.profile):
        source = restricted_environment(os.environ, spec.env)
    else:
        source = child_environment(spec.env)
    env = {key: val for key, val in source.items() if key not in REMOVED_ENV_VARS}
    env.update(
        {
            "VARDE_AGENT_ID": spec.agent_id or spec.workspace_id,
            "VARDE_HARNESS": "claude-cli",
            "CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS": "1",
        }
    )
    env.update(extra or {})
    return env


def _inspect_process(pid: int, _command: list[str]) -> ProcessIdentity | None:
    return process_state.inspect_process(pid, "Claude")


def _process_group_exists(process_group: int) -> bool:
    return process_state.process_group_exists(process_group)


class ClaudeCliPlugin:
    config_table = "claude_cli"
    capabilities = RunnerCapabilities(
        resume=True,
        permission_commands=True,
        usage=True,
        idle_status=True,
        persistent_process=True,
        interrupt=True,
        respond=True,
        restricted_profile=True,
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
        self.executable = str(executable) if executable else shutil.which("claude")
        self.interrupt_timeout = interrupt_timeout
        self.stop_timeout = stop_timeout
        self.process_inspector = process_inspector
        self.process_group_exists = process_group_exists
        self.process_group_signal = process_group_signal
        self.state_dir = (
            Path(state_dir) if state_dir else adapter_state_root() / "claude-cli"
        )
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._queues: dict[str, asyncio.Queue[RunnerEvent | None]] = {}
        self._readers: dict[str, asyncio.Task[None]] = {}
        self._stderr_readers: dict[str, asyncio.Task[None]] = {}
        self._pending: dict[str, set[str]] = {}
        self._permission_inputs: dict[str, dict[str, dict[str, Any]]] = {}
        self._answered: dict[str, set[str]] = {}
        self._status: dict[str, str] = {}
        self._specs: dict[str, SessionSpec] = {}
        self._stderr: dict[str, deque[str]] = {}
        self._stopping_pids: set[int] = set()
        self._interrupt_responses: dict[str, asyncio.Future[None]] = {}

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
            raise RuntimeError("claude executable not found on PATH")
        session_id = str(uuid.uuid4())
        ref = SessionRef(spec.provider, session_id)
        self._specs[session_id] = spec
        self._initialize_session(session_id)
        try:
            self._persist_spec(session_id, spec)
            await self._spawn(ref, resume_id=None)
            if spec.prompt:
                await self.send(ref, spec.prompt)
        except BaseException:
            await self.stop(ref)
            self._specs.pop(session_id, None)
            self._remove_spec(session_id)
            self._clear_live_state(session_id)
            raise
        return ref

    def _initialize_session(self, session_id: str) -> None:
        self._queues[session_id] = asyncio.Queue()
        self._pending[session_id] = set()
        self._permission_inputs[session_id] = {}
        self._answered[session_id] = set()
        self._stderr[session_id] = deque(maxlen=20)
        self._status[session_id] = "idle"

    def _spec_path(self, session_id: str) -> Path:
        return process_state.spec_path(self.state_dir, session_id, "Claude")

    def _persist_spec(self, session_id: str, spec: SessionSpec) -> None:
        process_state.persist_spec(self._spec_path(session_id), spec)

    def _load_spec(self, ref: SessionRef) -> SessionSpec:
        spec = self._specs.get(ref.session_id)
        if spec is not None:
            return spec
        try:
            value = json.loads(self._spec_path(ref.session_id).read_text())
        except (OSError, ValueError, TypeError) as exc:
            raise RuntimeError(
                f"cannot restore Claude session {ref.session_id}: persisted session "
                "metadata is unavailable"
            ) from exc
        if not isinstance(value, dict):
            raise TypeError("persisted Claude session metadata must be an object")
        try:
            fields = SessionSpec.__dataclass_fields__
            spec = SessionSpec(**{key: value[key] for key in fields if key in value})
        except TypeError as exc:
            raise RuntimeError("persisted Claude session metadata is invalid") from exc
        if spec.provider != ref.provider:
            raise RuntimeError("persisted Claude session provider does not match ref")
        self._specs[ref.session_id] = spec
        return spec

    def _remove_spec(self, session_id: str) -> None:
        with contextlib.suppress(RuntimeError):
            self._spec_path(session_id).unlink(missing_ok=True)
            self._settings_path(session_id).unlink(missing_ok=True)

    def _settings_path(self, session_id: str) -> Path:
        return self._spec_path(session_id).with_suffix(".bot-settings.json")

    def _restricted_flags(self, session_id: str) -> list[str]:
        path = self._settings_path(session_id)
        process_state.write_state(path, wire.restricted_settings())
        tools = wire.tool_names(restricted_profile().tool_kinds)
        return wire.restricted_flags(str(path), tools)

    def set_env_overlay(self, ref: SessionRef, env: dict[str, str]) -> None:
        """Set the env overlay (a re-issued bot token) before a spawn or resume."""
        spec = self._load_spec(ref)
        if is_restricted(spec.profile):
            check_restricted_overlay(env)
        self._specs[ref.session_id] = replace(spec, env=dict(env))

    def remove_spec(self, session_id: str) -> None:
        self._specs.pop(session_id, None)
        self._remove_spec(session_id)

    async def _spawn(self, ref: SessionRef, resume_id: str | None) -> None:
        if not self.executable:
            raise RuntimeError("claude executable not found on PATH")
        spec = self._specs[ref.session_id]
        restricted = is_restricted(spec.profile)
        if spec.profile is not None and not restricted:
            raise RuntimeError(f"unsupported session profile: {spec.profile}")
        # A restricted session always runs in the bot mode, whatever the spec says.
        mode = "bot" if restricted else spec.mode_id or "auto"
        command = wire.build_command(
            spec.model, spec.reasoning_effort, mode, ref.session_id, resume_id
        )
        if restricted:
            command.extend(self._restricted_flags(ref.session_id))
        command[0] = self.executable
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=spec.cwd,
                env=child_env(spec),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                limit=16 * 1024 * 1024,
            )
        except OSError as exc:
            raise RuntimeError("Claude executable could not be started") from exc
        self._processes[ref.session_id] = process
        identity = self.process_inspector(process.pid, command)
        if identity is None:
            raise RuntimeError("Claude process identity could not be inspected")
        self._persist_process(ref.session_id, process.pid, command, identity)
        self._status[ref.session_id] = "idle"
        self._stderr_readers[ref.session_id] = asyncio.create_task(
            self._drain_stderr(ref.session_id, process)
        )
        self._readers[ref.session_id] = asyncio.create_task(self._read(ref, process))

    async def _drain_stderr(
        self, session_id: str, process: asyncio.subprocess.Process
    ) -> None:
        if process.stderr is None:
            raise RuntimeError("Claude process stderr pipe is unavailable")
        try:
            while line := await process.stderr.readline():
                self._stderr[session_id].append(line.decode(errors="replace").rstrip())
        except ValueError:
            self._stderr[session_id].append(
                "[stderr line exceeded the 16 MiB reader limit; truncated]"
            )
            while await process.stderr.read(64 * 1024):
                pass

    @staticmethod
    async def _next_stdout_line(
        stdout: asyncio.StreamReader,
        queue: asyncio.Queue[RunnerEvent | None],
        session_id: str,
    ) -> bytes:
        """Return the next stdout line; skip an oversized line and report it."""
        try:
            return await stdout.readuntil(b"\n")
        except asyncio.IncompleteReadError as exc:
            return exc.partial
        except asyncio.LimitOverrunError as exc:
            await queue.put(
                _event(
                    "error",
                    session_id,
                    {"message": f"Claude stdout line exceeded the reader limit: {exc}"},
                )
            )
            overrun = exc
        # Discard the rest of the oversized line, then resume at the next one.
        while True:
            await stdout.readexactly(overrun.consumed)
            try:
                await stdout.readuntil(b"\n")
            except asyncio.IncompleteReadError:
                return b""
            except asyncio.LimitOverrunError as exc:
                overrun = exc
                continue
            return await ClaudeCliPlugin._next_stdout_line(stdout, queue, session_id)

    async def _read(self, ref: SessionRef, process: asyncio.subprocess.Process) -> None:
        if process.stdout is None:
            raise RuntimeError("Claude process stdout pipe is unavailable")
        session_id = ref.session_id
        queue = self._queues[session_id]
        try:
            line = await self._next_stdout_line(process.stdout, queue, session_id)
            while line:
                raw_line = line.decode(errors="replace")
                self._handle_interrupt_response(raw_line)
                for parsed_event in wire.parse_line(raw_line, session_id):
                    event = parsed_event
                    if event.kind == "permission_requested":
                        request_id = event.payload.get("request_id")
                        if isinstance(request_id, str):
                            self._pending[session_id].add(request_id)
                            self._permission_inputs[session_id][request_id] = {
                                "input": event.payload.get("input", {}),
                                "tool_use_id": event.payload.get("tool_use_id"),
                            }
                            if not is_restricted(self._specs[session_id].profile):
                                # The bot hook reads the command and drops it.
                                event = process_state.without_payload_field(
                                    event, "input"
                                )
                    if event.kind == "tool_intent":
                        event = process_state.redact_tool_input(event)
                    if event.kind == "status":
                        self._status[session_id] = str(
                            event.payload.get("status", "unknown")
                        )
                    await queue.put(event)
                line = await self._next_stdout_line(process.stdout, queue, session_id)
        finally:
            await process.wait()
            if not self.process_group_exists(process.pid):
                process_state.clear_process_record(
                    self.state_dir, session_id, process.pid
                )
            stderr_task = self._stderr_readers.get(session_id)
            if stderr_task is not None:
                await asyncio.gather(stderr_task, return_exceptions=True)
            expected_stop = process.pid in self._stopping_pids
            if not expected_stop and self._status.get(session_id) != "idle":
                await queue.put(
                    _event(
                        "error",
                        session_id,
                        {
                            "message": "Claude process exited unexpectedly",
                            "returncode": process.returncode,
                            "stderr": list(self._stderr.get(session_id, ())),
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
                self._status[session_id] = "error"
            elif expected_stop:
                self._status[session_id] = "idle"
            await queue.put(None)
            self._retire_process(session_id, process)

    def _handle_interrupt_response(self, line: str) -> None:
        try:
            frame = json.loads(line)
        except ValueError, TypeError:
            return
        if not isinstance(frame, dict) or frame.get("type") != "control_response":
            return
        response = frame.get("response")
        request_id = response.get("request_id") if isinstance(response, dict) else None
        if not isinstance(request_id, str):
            return
        future = self._interrupt_responses.get(request_id)
        if future is None or future.done():
            return
        if not isinstance(response, dict) or response.get("subtype") != "success":
            future.set_exception(RuntimeError("Claude rejected interrupt request"))

    async def send(self, ref: SessionRef, prompt: str) -> None:
        process = self._live_process(ref)
        if process.stdin is None:
            raise RuntimeError("Claude process stdin pipe is unavailable")
        process.stdin.write((wire.encode_user_message(prompt) + "\n").encode())
        await process.stdin.drain()
        self._status[ref.session_id] = "running"

    def _live_process(self, ref: SessionRef) -> asyncio.subprocess.Process:
        process = self._processes.get(ref.session_id)
        if process is None or process.returncode is not None:
            raise RuntimeError("Claude process is not running")
        return process

    async def idle_status(self, ref: SessionRef) -> str:
        return self._status.get(ref.session_id, "unknown")

    def process_alive(self, ref: SessionRef) -> bool:
        process = self._processes.get(ref.session_id)
        return process is not None and process.returncode is None

    async def events(self, ref: SessionRef) -> AsyncGenerator[RunnerEvent]:
        queue = self._queues.setdefault(ref.session_id, asyncio.Queue())
        while True:
            event = await queue.get()
            if event is None:
                return
            yield event

    async def respond_permission(
        self, ref: SessionRef, request_id: str, decision: str
    ) -> None:
        process = self._live_process(ref)
        if process.stdin is None:
            raise RuntimeError("Claude process stdin pipe is unavailable")
        answered = self._answered.setdefault(ref.session_id, set())
        if request_id in answered:
            return
        pending = self._pending.get(ref.session_id, set())
        allow = decision.lower() in {"allow", "approve", "approved"}
        allow = allow and request_id in pending
        permission = self._permission_inputs.get(ref.session_id, {}).get(request_id, {})
        original_input = permission.get("input")
        if not isinstance(original_input, dict):
            original_input = {}
        payload = (
            wire.encode_control_response(
                request_id,
                allow,
                original_input,
                None if allow else "Permission denied",
            )
            + "\n"
        ).encode()
        answered.add(request_id)
        try:
            process.stdin.write(payload)
            await process.stdin.drain()
        except BrokenPipeError, ConnectionError, OSError:
            answered.discard(request_id)
            raise RuntimeError(
                "Claude permission response could not be delivered"
            ) from None

    async def interrupt(self, ref: SessionRef) -> None:
        process = self._live_process(ref)
        if process.stdin is None:
            raise RuntimeError("Claude process stdin pipe is unavailable")
        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._interrupt_responses[request_id] = future
        try:
            process.stdin.write((wire.encode_interrupt(request_id) + "\n").encode())
            await process.stdin.drain()
            await asyncio.wait_for(
                self._wait_idle(ref.session_id, process, future),
                self.interrupt_timeout,
            )
        except TimeoutError as exc:
            raise TimeoutError("Claude interrupt timed out") from exc
        finally:
            self._interrupt_responses.pop(request_id, None)
            if not future.done():
                future.cancel()

    async def _wait_idle(
        self,
        session_id: str,
        process: asyncio.subprocess.Process,
        interrupt_response: asyncio.Future[None],
    ) -> None:
        while self._status.get(session_id) == "running":
            if interrupt_response.done():
                interrupt_response.result()
            if process.returncode is not None:
                raise RuntimeError("Claude process exited during interrupt")
            await asyncio.sleep(0.02)
        if process.returncode is not None:
            raise RuntimeError("Claude process exited during interrupt")
        if self._status.get(session_id) != "idle":
            raise RuntimeError("Claude interrupt ended without an idle status")
        if interrupt_response.done():
            interrupt_response.result()

    def validate_resume_mode(self, mode: str) -> None:
        if mode not in wire.MODE_MAP:
            raise ValueError(f"unsupported runner mode: {mode}")

    async def resume(
        self, ref: SessionRef, settings: ResumeSettings | None = None
    ) -> SessionRef:
        spec = self._load_spec(ref)
        if self._is_unavailable(ref.session_id):
            raise RuntimeError(f"Claude session {ref.session_id} is unavailable")
        if settings is not None and settings.mode_id is not None:
            if is_restricted(spec.profile):
                raise ValueError("a restricted session cannot change mode")
            self.validate_resume_mode(settings.mode_id)
            spec = replace(spec, mode_id=settings.mode_id)
            self._persist_spec(ref.session_id, spec)
        process = self._processes.get(ref.session_id)
        if process is not None:
            await self.stop(ref)
        elif not await self._recover_orphan(ref.session_id):
            raise RuntimeError(
                "persisted Claude process for "
                f"{ref.session_id} is unavailable or mismatched"
            )
        self._initialize_session(ref.session_id)
        self._specs[ref.session_id] = spec
        await self._spawn(ref, resume_id=ref.session_id)
        return ref

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
            product="Claude",
            inspect=self.process_inspector,
            signal_group=self.process_group_signal,
            group_exists=self.process_group_exists,
            timeout=self.stop_timeout,
            mark_unavailable=lambda sid, value, reason: process_state.mark_unavailable(
                self.state_dir, sid, value, reason, "Claude"
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
        """Sweep persisted Claude processes before the supervisor resumes sessions."""
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
        process = self._processes.get(ref.session_id)
        if process is None:
            return
        reader = self._readers.get(ref.session_id)
        stderr_reader = self._stderr_readers.get(ref.session_id)
        self._stopping_pids.add(process.pid)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        if not await self._wait_for_group_exit(process.pid, self.stop_timeout):
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            if not await self._wait_for_group_exit(process.pid, self.stop_timeout):
                raise RuntimeError("Claude process group did not exit")
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
        if self._processes.get(session_id) is not process:
            return
        self._processes.pop(session_id, None)
        self._readers.pop(session_id, None)
        self._stderr_readers.pop(session_id, None)
        self._pending.pop(session_id, None)
        self._permission_inputs.pop(session_id, None)
        self._answered.pop(session_id, None)
        self._stderr.pop(session_id, None)
        self._stopping_pids.discard(process.pid)

    def _clear_live_state(self, session_id: str) -> None:
        for mapping in (
            self._processes,
            self._readers,
            self._stderr_readers,
            self._pending,
            self._permission_inputs,
            self._answered,
            self._queues,
            self._status,
            self._stderr,
        ):
            mapping.pop(session_id, None)

    async def close(self) -> None:
        refs = [
            SessionRef(self._specs[session_id].provider, session_id)
            for session_id in list(self._processes)
            if session_id in self._specs
        ]
        await asyncio.gather(*(self.stop(ref) for ref in refs))


def _event(kind: EventKind, session_id: str, payload: dict[str, Any]) -> RunnerEvent:
    return RunnerEvent(
        kind=kind, session_id=session_id, payload=payload, provider_id="claude-cli"
    )

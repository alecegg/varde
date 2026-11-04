"""Supervised Node host process: spawn, frames, request ids, crash policy, lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import signal
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from varde_runner.node_host import orphans
from varde_runner.node_host.errors import (
    CallTimeout,
    HostCallError,
    HostDown,
    HostRestarted,
    NodeHostError,
)
from varde_runner.node_host.frames import (
    MAX_LINE_BYTES,
    PROTOCOL_VERSION,
    Event,
    FrameError,
    Ready,
    Reply,
    encode_request,
    parse_frame,
)
from varde_runner.node_host.node_version import MIN_NODE, node_version_supported
from varde_runner.node_host.policy import GiveUp, RestartPolicy, next_action
from varde_runner.plugins import child_environment

logger = logging.getLogger(__name__)

HostState = Literal["starting", "ready", "restarting", "down"]
RestartCallback = Callable[[], Awaitable[None] | None]

STDERR_TAIL_LINES = 200
STDERR_LINE_CHARS = 2000
SYNTHETIC_SEQ = -1


@dataclass(slots=True)
class _Run:
    """One launched child process and everything tied to its lifetime."""

    process: asyncio.subprocess.Process
    pending: dict[int, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)
    tracked: dict[int, orphans.GroupRecord] = field(default_factory=dict)
    ready: asyncio.Future[Ready] = field(default_factory=asyncio.Future)
    done: asyncio.Future[None] = field(default_factory=asyncio.Future)
    intentional: bool = False
    tasks: list[asyncio.Task[None]] = field(default_factory=list)
    watcher: asyncio.Task[None] | None = None
    host_record: orphans.GroupRecord | None = None

    @property
    def pgid(self) -> int:
        return self.process.pid


def _signal_group(process_group: int, sig: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process_group, sig)


class Subscription:
    """Async iterator of events for one session id (None: host-level events)."""

    def __init__(self, host: NodeHost, key: str | None) -> None:
        self._host = host
        self._key = key
        self._queue: asyncio.Queue[Event | None] = asyncio.Queue()
        host._subscribers.setdefault(key, set()).add(self)

    def __aiter__(self) -> Subscription:
        return self

    async def __anext__(self) -> Event:
        event = await self._queue.get()
        if event is None:
            raise StopAsyncIteration
        return event

    def put(self, event: Event) -> None:
        self._queue.put_nowait(event)

    def close(self) -> None:
        self._host._subscribers.get(self._key, set()).discard(self)
        self._queue.put_nowait(None)


class NodeHost:
    def __init__(  # noqa: PLR0913 - spec'd constructor plus tuning seams.
        self,
        command: Sequence[str],
        engine_path: str | Path,
        env: Mapping[str, str] | None = None,
        policy: RestartPolicy | None = None,
        *,
        state_path: Path | None = None,
        call_timeout_s: float = 60.0,
        ready_timeout_s: float = 15.0,
        stop_grace_s: float = 5.0,
    ) -> None:
        self._command = list(command)
        self._engine_path = str(engine_path)
        self._env = env
        self._policy = policy or RestartPolicy()
        self._state_path = state_path
        self._call_timeout_s = call_timeout_s
        self._ready_timeout_s = ready_timeout_s
        self._stop_grace_s = stop_grace_s
        self._state: HostState = "down"
        self._down_reason = "not started"
        self._run: _Run | None = None
        self._history: list[float] = []
        self._next_id = 0
        self._callbacks: list[RestartCallback] = []
        self._subscribers: dict[str | None, set[Subscription]] = {}
        self._stderr: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        self._lock = asyncio.Lock()
        self._recovery: asyncio.Task[None] | None = None

    @property
    def state(self) -> HostState:
        return self._state

    @property
    def down_reason(self) -> str:
        return self._down_reason

    @property
    def pid(self) -> int | None:
        return self._run.process.pid if self._run else None

    def stderr_tail(self) -> list[str]:
        return list(self._stderr)

    def on_restart(self, callback: RestartCallback) -> None:
        """Run ``callback`` after a restart; it must not call restart() or stop()."""
        self._callbacks.append(callback)

    def subscribe(self, session_id: str | None) -> Subscription:
        return Subscription(self, session_id)

    async def start(self) -> None:
        async with self._lock:
            if self._state != "down" or self._run is not None:
                raise NodeHostError(f"host cannot start from state {self._state}")
            self._history.clear()
            if self._state_path is not None:
                try:
                    await orphans.reap_orphans(self._state_path)
                except OSError as exc:
                    self._set_down(f"cannot read host record: {exc}")
                    raise NodeHostError(self._down_reason) from exc
            self._set_state("starting", "start")
            try:
                self._run = await self._launch()
            except NodeHostError as exc:
                self._set_down(str(exc))
                raise
            self._set_state("ready", "started")

    async def call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        run = self._run
        if self._state == "down":
            raise HostDown(self._down_reason)
        if self._state != "ready" or run is None or run.process.stdin is None:
            raise HostRestarted(f"host is {self._state}")
        self._next_id += 1
        request_id = self._next_id
        line = encode_request(request_id, method, params or {})
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        run.pending[request_id] = future
        try:
            run.process.stdin.write(line)
            await run.process.stdin.drain()
            return await asyncio.wait_for(future, timeout_s or self._call_timeout_s)
        except TimeoutError:
            raise CallTimeout(f"{method} did not reply in time") from None
        except BrokenPipeError, ConnectionResetError:
            raise HostRestarted("host closed its input") from None
        finally:
            run.pending.pop(request_id, None)

    async def restart(self) -> None:
        """Replace the child now and reset the crash history."""
        async with self._lock:
            await self._cancel_recovery()
            self._history.clear()
            old, self._run = self._run, None
            self._set_state("restarting", "explicit restart")
            if old is not None:
                await self._terminate(old, HostRestarted("host restarted"))
            try:
                self._run = await self._launch()
            except NodeHostError as exc:
                self._set_down(str(exc))
                raise
            self._set_state("ready", "restarted")
        await self._run_callbacks()

    async def stop(self) -> None:
        async with self._lock:
            await self._cancel_recovery()
            old, self._run = self._run, None
            if old is not None:
                await self._terminate(old, HostDown("host stopped"))
            self._set_down("stopped")
            for subscribers in list(self._subscribers.values()):
                for subscription in list(subscribers):
                    subscription.close()

    def _set_state(self, state: HostState, reason: str) -> None:
        self._state = state
        logger.info("node_host_state state=%s reason=%s", state, reason)
        self._publish(
            Event("host_state", None, {"state": state, "reason": reason}, SYNTHETIC_SEQ)
        )

    def _set_down(self, reason: str) -> None:
        self._down_reason = reason
        self._set_state("down", reason)

    def _publish(self, event: Event) -> None:
        for subscription in list(self._subscribers.get(event.session, ())):
            subscription.put(event)

    def _frame_error(self, message: str) -> None:
        logger.warning("node_host_frame_error message=%s", message)
        self._publish(
            Event("host_frame_error", None, {"message": message}, SYNTHETIC_SEQ)
        )

    async def _launch(self) -> _Run:
        argv = [*self._command, self._engine_path]
        env = dict(self._env) if self._env is not None else child_environment()
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
                limit=MAX_LINE_BYTES + 1,
            )
        except OSError as exc:
            raise NodeHostError(f"cannot start node host {argv[0]}: {exc}") from exc
        run = _Run(process)
        run.tasks = [
            asyncio.create_task(self._read_stdout(run)),
            asyncio.create_task(self._read_stderr(run)),
        ]
        run.watcher = asyncio.create_task(self._watch(run))
        try:
            await self._record_host(run, argv)
            await asyncio.wait_for(asyncio.shield(run.ready), self._ready_timeout_s)
        except TimeoutError:
            await self._terminate(run, HostRestarted("host never became ready"))
            raise NodeHostError(
                self._with_stderr("host did not send ready in time")
            ) from None
        except OSError as exc:
            await self._terminate(run, HostRestarted("host record failed"))
            raise NodeHostError(f"cannot persist host record: {exc}") from exc
        except NodeHostError:
            await self._terminate(run, HostRestarted("host failed to start"))
            raise
        return run

    def _with_stderr(self, message: str) -> str:
        tail = " | ".join(list(self._stderr)[-5:])
        return f"{message}; stderr: {tail}" if tail else message

    async def _record_host(self, run: _Run, argv: list[str]) -> None:
        if self._state_path is None:
            return
        group = await asyncio.to_thread(
            orphans.identify_group, run.pgid, run.pgid, argv
        )
        await asyncio.to_thread(orphans.write_record, self._state_path, group, [])
        run.host_record = group

    async def _persist_tracked(self, run: _Run) -> None:
        if self._state_path is None:
            return
        groups = list(run.tracked.values())
        try:
            await asyncio.to_thread(
                orphans.write_record, self._state_path, run.host_record, groups
            )
        except OSError:
            logger.exception("node_host_record_write_failed")

    async def _read_stdout(self, run: _Run) -> None:
        stream = run.process.stdout
        assert stream is not None  # noqa: S101 - PIPE requested at spawn.
        try:
            while line := await stream.readline():
                await self._handle_line(run, line.rstrip(b"\n"))
        except ValueError:
            self._frame_error("host line exceeds the frame limit")
            _signal_group(run.pgid, signal.SIGKILL)

    async def _handle_line(self, run: _Run, line: bytes) -> None:
        try:
            frame = parse_frame(line)
        except FrameError as exc:
            self._frame_error(str(exc))
            return
        if isinstance(frame, Ready):
            self._accept_ready(run, frame)
        elif isinstance(frame, Reply):
            self._resolve(run, frame)
        else:
            await self._deliver(run, frame)

    def _accept_ready(self, run: _Run, ready: Ready) -> None:
        if run.ready.done():
            self._frame_error("duplicate ready frame")
            return
        if ready.protocol != PROTOCOL_VERSION:
            run.ready.set_exception(
                NodeHostError(f"unsupported host protocol {ready.protocol}")
            )
        elif not node_version_supported(ready.node):
            minimum = ".".join(map(str, MIN_NODE))
            run.ready.set_exception(
                NodeHostError(f"Node {ready.node} is older than {minimum}")
            )
        else:
            run.ready.set_result(ready)

    def _resolve(self, run: _Run, reply: Reply) -> None:
        future = run.pending.get(reply.id)
        if future is None or future.done():
            return
        if reply.error is not None:
            future.set_exception(HostCallError(*reply.error))
        else:
            future.set_result(reply.result or {})

    async def _deliver(self, run: _Run, event: Event) -> None:
        if event.event == "child_tracked":
            await self._track(run, event)
        elif event.event == "child_untracked":
            pgid = event.data.get("pgid")
            if isinstance(pgid, int):
                run.tracked.pop(pgid, None)
            await self._persist_tracked(run)
        self._publish(event)

    async def _track(self, run: _Run, event: Event) -> None:
        pid, pgid = event.data.get("pid"), event.data.get("pgid")
        if not (isinstance(pid, int) and isinstance(pgid, int) and pgid > 1):
            self._frame_error("child_tracked needs integer pid and pgid")
            return
        run.tracked[pgid] = orphans.GroupRecord(pid, pgid)
        if self._state_path is not None:
            run.tracked[pgid] = await asyncio.to_thread(
                orphans.identify_group, pid, pgid
            )
        await self._persist_tracked(run)

    async def _read_stderr(self, run: _Run) -> None:
        stream = run.process.stderr
        assert stream is not None  # noqa: S101 - PIPE requested at spawn.
        partial = ""
        while chunk := await stream.read(65536):
            partial += chunk.decode("utf-8", errors="replace")
            *lines, partial = partial.split("\n")
            self._stderr.extend(line[:STDERR_LINE_CHARS] for line in lines)
            if len(partial) > STDERR_LINE_CHARS:
                self._stderr.append(partial[:STDERR_LINE_CHARS])
                partial = ""
        if partial:
            self._stderr.append(partial[:STDERR_LINE_CHARS])

    async def _watch(self, run: _Run) -> None:
        returncode = await run.process.wait()
        self._cleanup_groups(run)
        _, pending = await asyncio.wait(run.tasks, timeout=1.0)
        for task in pending:
            task.cancel()
        reason = f"host exited with code {returncode}"
        if not run.ready.done():
            run.ready.set_exception(NodeHostError(self._with_stderr(reason)))
        self._fail_pending(run, HostRestarted(reason))
        run.done.set_result(None)
        if not run.intentional and self._run is run:
            self._recovery = asyncio.create_task(self._recover(run, reason))

    def _cleanup_groups(self, run: _Run) -> None:
        _signal_group(run.pgid, signal.SIGKILL)
        for pgid in run.tracked:
            _signal_group(pgid, signal.SIGKILL)
        if self._state_path is not None:
            orphans.clear_record(self._state_path)

    @staticmethod
    def _fail_pending(run: _Run, error: NodeHostError) -> None:
        for future in run.pending.values():
            if not future.done():
                future.set_exception(error)

    async def _recover(self, dead: _Run, reason: str) -> None:
        self._run = None
        self._history.append(time.monotonic())
        while True:
            action = next_action(self._history, time.monotonic(), self._policy)
            if isinstance(action, GiveUp):
                self._give_up(action, reason)
                return
            self._set_state("restarting", reason)
            await asyncio.sleep(action.delay_s)
            try:
                self._run = await self._launch()
            except NodeHostError as exc:
                reason = str(exc)
                self._history.append(time.monotonic())
                continue
            self._set_state("ready", "restarted after crash")
            await self._run_callbacks()
            return

    def _give_up(self, action: GiveUp, reason: str) -> None:
        deaths, window = action.deaths_in_window, self._policy.window_s
        message = f"{deaths} host deaths in {window:g}s: {reason}"
        self._down_reason = message
        self._state = "down"
        logger.error("node_host_down reason=%s", message)
        data = {"reason": message, "stderr_tail": self.stderr_tail()}
        self._publish(
            Event(
                "host_state", None, {"state": "down", "reason": message}, SYNTHETIC_SEQ
            )
        )
        self._publish(Event("host_down", None, data, SYNTHETIC_SEQ))

    async def _run_callbacks(self) -> None:
        for callback in list(self._callbacks):
            try:
                outcome = callback()
                if inspect.isawaitable(outcome):
                    await outcome
            except Exception:
                logger.exception("node_host_restart_callback_failed")

    async def _cancel_recovery(self) -> None:
        task, self._recovery = self._recovery, None
        if task is None or task is asyncio.current_task():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _terminate(self, run: _Run, error: NodeHostError) -> None:
        run.intentional = True
        self._fail_pending(run, error)
        if run.process.returncode is None:
            _signal_group(run.pgid, signal.SIGTERM)
            try:
                await asyncio.wait_for(run.process.wait(), self._stop_grace_s)
            except TimeoutError:
                _signal_group(run.pgid, signal.SIGKILL)
        await run.done

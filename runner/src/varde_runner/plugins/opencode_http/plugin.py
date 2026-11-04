"""OpenCode server HTTP/SSE adapter."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import re
import secrets
import shutil
import signal
import socket
import urllib.error
import urllib.request
import uuid
from collections.abc import AsyncGenerator, Callable
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
from varde_runner.plugins.opencode_http import wire
from varde_runner.plugins.process_state import (
    inspect_process,
    process_group_exists,
    wait_for_group_exit,
)
from varde_runner.protocol import ResumeSettings, UnsupportedCapability

MIN_VERSION = (2, 0, 18)
MAX_VERSION = (3, 0, 0)
REQUIRED_ROUTES = {
    ("POST", "/api/session"),
    ("GET", "/api/session/{sessionID}"),
    ("POST", "/api/session/{sessionID}/prompt"),
    ("POST", "/api/session/{sessionID}/interrupt"),
    ("GET", "/api/event"),
    ("GET", "/api/permission/request"),
    ("GET", "/api/form"),
    ("POST", "/api/session/{sessionID}/permission/{requestID}/reply"),
    ("POST", "/api/session/{sessionID}/form/{formID}/reply"),
    ("DELETE", "/api/session/{sessionID}/form/{formID}"),
}


class OpenCodeHttpPlugin:
    config_table = "opencode_http"
    capabilities = RunnerCapabilities(
        resume=True,
        usage=True,
        idle_status=True,
        persistent_process=True,
        interrupt=True,
        respond=True,
    )

    def __init__(
        self,
        executable: str | None = None,
        *,
        state_dir: str | Path | None = None,
        identity_reader: Callable[[int], tuple[str, str] | None] | None = None,
    ) -> None:
        self.executable = executable or shutil.which("opencode")
        self.state_dir = Path(state_dir or adapter_state_root() / "opencode-http")
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._identity_reader = identity_reader or _process_identity
        self._servers: dict[str, dict[str, Any]] = {}
        self._queues: dict[str, asyncio.Queue[RunnerEvent | None]] = {}
        self._streams: dict[str, asyncio.Task[None]] = {}
        self._stderr_readers: dict[str, asyncio.Task[None]] = {}
        self._specs: dict[str, SessionSpec] = {}
        self._pending: dict[str, dict[str, str]] = {}
        self._resolved: dict[str, set[str]] = {}
        self._settled: dict[str, asyncio.Event] = {}
        self._passwords: dict[str, str] = {}

    def session_settings(self, model: Model) -> SessionSettings:
        return SessionSettings(model.model, model.reasoning_effort, model.mode)

    async def start(self, spec: SessionSpec) -> SessionRef:
        mode = spec.mode_id or "workspace-write"
        if mode not in wire.MODE_RULES:
            raise RuntimeError(f"unsupported OpenCode mode: {mode}")
        if not self.executable:
            raise RuntimeError("opencode executable not found on PATH")
        sid = str(uuid.uuid4())
        ref = SessionRef(spec.provider, sid)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        port = _free_port()
        password = secrets.token_urlsafe(32)
        env = child_environment()
        env.update(
            {
                "OPENCODE_PASSWORD": password,
                "VARDE_AGENT_ID": spec.agent_id or spec.workspace_id,
                "VARDE_HARNESS": "opencode-http",
            }
        )
        process = await asyncio.create_subprocess_exec(
            self.executable,
            "serve",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(port),
            cwd=spec.cwd,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        server = {
            "process": process,
            "base": f"http://127.0.0.1:{port}",
            "password": password,
            "pid": process.pid,
        }
        self._servers[sid] = server
        self._passwords[sid] = password
        self._specs[sid] = spec
        self._queues[sid] = asyncio.Queue()
        self._pending[sid] = {}
        self._resolved[sid] = set()
        self._settled[sid] = asyncio.Event()
        self._settled[sid].set()
        server["connected"] = asyncio.Event()
        server["stop"] = asyncio.Event()
        identity = self._identity_reader(process.pid)
        if identity is None:
            await _terminate_process_group(process.pid)
            await process.wait()
            self._servers.pop(sid, None)
            stderr_task = self._stderr_readers.pop(sid, None)
            if stderr_task:
                stderr_task.cancel()
                await asyncio.gather(stderr_task, return_exceptions=True)
            raise RuntimeError("OpenCode process identity could not be inspected")
        self._stderr_readers[sid] = asyncio.create_task(self._drain_stderr(process))
        self._save(
            sid,
            {
                "pid": process.pid,
                "identity": list(identity),
                "command": identity[1],
                "owner_pid": os.getpid(),
                "owner_identity": _identity_json(self._identity_reader(os.getpid())),
                "port": port,
                "session_id": None,
                "cwd": spec.cwd,
                "workspace_id": spec.workspace_id,
                "agent_id": spec.agent_id,
                "executable": self.executable,
            },
        )
        try:
            await self._wait_ready(server)
            result = await self._request(
                server, "POST", "/api/session", wire.encode_session(spec, mode)
            )
            data = result.get("data", result)
            session_id = data["id"]
            server["session_id"] = session_id
            self._save(
                sid,
                {
                    "pid": process.pid,
                    "identity": list(identity),
                    "command": identity[1],
                    "owner_pid": os.getpid(),
                    "owner_identity": _identity_json(
                        self._identity_reader(os.getpid())
                    ),
                    "port": port,
                    "session_id": session_id,
                    "cwd": spec.cwd,
                    "workspace_id": spec.workspace_id,
                    "agent_id": spec.agent_id,
                    "executable": self.executable,
                },
            )
            self._streams[sid] = asyncio.create_task(self._events(ref, server))
            try:
                await asyncio.wait_for(server["connected"].wait(), 10)
            except TimeoutError as exc:
                raise RuntimeError("OpenCode SSE subscription did not connect") from exc
            if spec.prompt:
                await self.send(ref, spec.prompt)
            return SessionRef(spec.provider, sid)
        except BaseException:
            await self.stop(ref)
            raise

    def _path(self, sid: str) -> Path:
        return self.state_dir / f"{sid}.json"

    def _save(self, sid: str, record: dict[str, Any]) -> None:
        self._write_record(self._path(sid), record)

    @staticmethod
    def _write_record(path: Path, record: dict[str, Any]) -> None:
        temp = path.with_suffix(".tmp")
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
        os.replace(temp, path)

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        if process.stderr:
            while await process.stderr.readline():
                pass

    async def recover_orphans(self) -> set[str]:
        """Recover persisted servers before Supervisor attempts session resume."""
        unavailable: set[str] = set()
        for path in self.state_dir.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                session_id = str(uuid.UUID(path.stem))
                owner_pid = record.get("owner_pid")
                if _owner_is_alive(
                    owner_pid, record.get("owner_identity"), self._identity_reader
                ):
                    continue
                if not record.get("session_id"):
                    path.unlink(missing_ok=True)
                    continue
                pid = record.get("pid")
                actual = self._identity_reader(pid) if isinstance(pid, int) else None
                if _recorded_process_matches(record, actual):
                    await _terminate_process_group(pid)
                record.update(pid=None, identity=None, command=None)
                self._write_record(path, record)
                self._servers.pop(session_id, None)
                unavailable.discard(session_id)
            except OSError, ValueError, TypeError:
                path.unlink(missing_ok=True)
                unavailable.add(path.stem)
        return unavailable

    async def _wait_ready(self, server: dict[str, Any]) -> None:
        for _ in range(100):
            process = server.get("process")
            if process and process.returncode is not None:
                raise RuntimeError("opencode serve exited before becoming ready")
            try:
                info = await self._request(server, "GET", "/api/info")
            except OSError, urllib.error.URLError:
                await asyncio.sleep(0.1)
                continue
            version_text = info.get("version")
            if not isinstance(version_text, str):
                raise TypeError("OpenCode /api/info did not include a version")
            version = _version(version_text)
            if not MIN_VERSION <= version < MAX_VERSION:
                raise RuntimeError(
                    f"OpenCode version {version_text} unsupported; "
                    "require >=2.0.18 and <3.0.0"
                )
            try:
                spec = await self._request(server, "GET", "/openapi.json")
            except OSError, urllib.error.URLError:
                await asyncio.sleep(0.1)
                continue
            paths = spec.get("paths", {})
            missing = sorted(
                f"{method} {path}"
                for method, path in REQUIRED_ROUTES
                if not _has_route(paths, method, path)
            )
            if missing:
                raise RuntimeError(
                    "OpenCode API is missing required routes: " + ", ".join(missing)
                )
            return
        raise RuntimeError("OpenCode server did not become ready")

    async def _request(
        self, server: dict[str, Any], method: str, path: str, body: Any = None
    ) -> dict[str, Any]:
        def request() -> dict[str, Any]:
            raw = json.dumps(body).encode() if body is not None else None
            auth = base64.b64encode(f"opencode:{server['password']}".encode()).decode()
            req = urllib.request.Request(  # noqa: S310 - base URL is loopback only.
                server["base"] + path,
                data=raw,
                method=method,
                headers={
                    "Authorization": f"Basic {auth}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as response:  # noqa: S310
                raw_response = response.read()
            return json.loads(raw_response or b"{}")

        return await asyncio.to_thread(request)

    async def send(self, ref: SessionRef, prompt: str) -> None:
        server = self._servers[ref.session_id]
        if not server["connected"].is_set():
            await asyncio.wait_for(server["connected"].wait(), 10)
        self._settled[ref.session_id].clear()
        try:
            await self._request(
                server,
                "POST",
                f"/api/session/{server['session_id']}/prompt",
                {"text": prompt},
            )
        except BaseException:
            self._settled[ref.session_id].set()
            raise

    async def _events(self, ref: SessionRef, server: dict[str, Any]) -> None:
        auth = base64.b64encode(f"opencode:{server['password']}".encode()).decode()
        request = urllib.request.Request(  # noqa: S310 - base URL is loopback only.
            server["base"] + "/api/event",
            headers={"Authorization": f"Basic {auth}", "Accept": "text/event-stream"},
        )
        failures = 0
        while not server["stop"].is_set() and failures < 6:
            try:
                response = await asyncio.to_thread(
                    urllib.request.urlopen, request, timeout=2
                )
                server["response"] = response
                await self._reconcile_requests(ref, server)
                buffer: list[str] = []
                while not server["stop"].is_set():
                    try:
                        line = await asyncio.to_thread(response.readline)
                    except TimeoutError:
                        continue
                    if not line:
                        if buffer:
                            await self._publish_sse(ref, server, "\n".join(buffer))
                            buffer.clear()
                        break
                    if line in {b"\n", b"\r\n"}:
                        if buffer:
                            data = "\n".join(buffer)
                            await self._publish_sse(ref, server, data)
                            buffer.clear()
                    elif line.startswith(b"data:"):
                        buffer.append(line[5:].decode(errors="replace").strip())
                response.close()
                failures = 0
            except OSError, urllib.error.URLError, TimeoutError:
                failures += 1
            if server["stop"].is_set():
                break
            await asyncio.sleep(min(0.1 * (2**failures), 2.0))
        if not server["stop"].is_set():
            await self._queues[ref.session_id].put(
                RunnerEvent(
                    "error",
                    ref.session_id,
                    {"message": "OpenCode SSE disconnected"},
                    "opencode-http",
                )
            )
            await self._queues[ref.session_id].put(None)

    async def _publish_sse(
        self, ref: SessionRef, server: dict[str, Any], data: str
    ) -> None:
        try:
            frame = json.loads(data)
        except ValueError, RecursionError:
            frame = None
        if isinstance(frame, dict) and frame.get("type") == "server.connected":
            server["connected"].set()
            return
        for event in wire.decode_sse(data, ref.session_id, server["session_id"]):
            self._track_request(ref.session_id, event)
            if event.kind == "status" and event.payload.get("status") == "running":
                self._settled[ref.session_id].clear()
            elif event.kind == "session_end":
                self._settled[ref.session_id].set()
            await self._queues[ref.session_id].put(event)

    async def _reconcile_requests(
        self, ref: SessionRef, server: dict[str, Any]
    ) -> None:
        for path, kind in (
            ("/api/permission/request", "permission"),
            ("/api/form", "question"),
        ):
            try:
                result = await self._request(server, "GET", path)
            except OSError, urllib.error.URLError:
                continue
            values = result.get("data", [])
            if isinstance(values, dict):
                values = list(values.values())
            if not isinstance(values, list):
                continue
            for value in values:
                if (
                    not isinstance(value, dict)
                    or value.get("sessionID") != server["session_id"]
                ):
                    continue
                if kind == "permission":
                    event_data = value
                    event_kind = "permission.asked"
                else:
                    event_data = {"sessionID": server["session_id"], "form": value}
                    event_kind = "form.created"
                await self._publish_sse(
                    ref, server, json.dumps({"type": event_kind, "data": event_data})
                )

    async def events(self, ref: SessionRef) -> AsyncGenerator[RunnerEvent]:
        queue = self._queues[ref.session_id]
        while (event := await queue.get()) is not None:
            yield event

    def _track_request(self, sid: str, event: RunnerEvent) -> None:
        if event.kind == "permission_requested":
            request_id = event.payload.get("request_id")
            kind = "permission"
        elif event.kind == "question_requested":
            request_id = event.payload.get("id")
            kind = "question"
        else:
            return
        if isinstance(request_id, str):
            self._pending.setdefault(sid, {})[request_id] = kind

    async def respond(
        self, ref: SessionRef, request_id: str, response: dict[str, Any]
    ) -> None:
        sid = ref.session_id
        if request_id in self._resolved.setdefault(sid, set()):
            return
        server = self._servers[ref.session_id]
        pending_kind = self._pending.setdefault(sid, {}).get(request_id)
        requested_kind = response.get("kind", pending_kind)
        if pending_kind is None:
            return
        try:
            if pending_kind == "question":
                answer = response.get("answer")
                if (
                    requested_kind != "question"
                    or not isinstance(answer, dict)
                    or not answer
                ):
                    await self._cancel_form(server, request_id)
                else:
                    await self._request(
                        server,
                        "POST",
                        f"/api/session/{server['session_id']}/form/{request_id}/reply",
                        {"answer": answer},
                    )
            elif pending_kind == "permission":
                decision = (
                    response.get("decision")
                    if requested_kind == "permission"
                    else "reject"
                )
                if decision not in {"once", "always", "reject"}:
                    decision = "reject"
                await self._request(
                    server,
                    "POST",
                    f"/api/session/{server['session_id']}/permission/{request_id}/reply",
                    {"decision": decision, "message": response.get("message")},
                )
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
        finally:
            self._pending[sid].pop(request_id, None)
            self._resolved[sid].add(request_id)

    async def _cancel_form(self, server: dict[str, Any], form_id: str) -> None:
        try:
            await self._request(
                server,
                "DELETE",
                f"/api/session/{server['session_id']}/form/{form_id}",
            )
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

    async def interrupt(self, ref: SessionRef) -> None:
        server = self._servers[ref.session_id]
        if self._settled[ref.session_id].is_set():
            return
        await self._request(
            server, "POST", f"/api/session/{server['session_id']}/interrupt", {}
        )
        try:
            await asyncio.wait_for(self._settled[ref.session_id].wait(), 10)
        except TimeoutError as exc:
            raise RuntimeError("OpenCode turn did not end after interrupt") from exc

    async def _deny_permission(self, server: dict[str, Any], request_id: str) -> None:
        await self._request(
            server,
            "POST",
            f"/api/session/{server['session_id']}/permission/{request_id}/reply",
            {"decision": "reject"},
        )

    def validate_resume_mode(self, mode: str) -> None:
        raise UnsupportedCapability(
            "OpenCode mode is fixed when the session is created"
        )

    async def resume(
        self, ref: SessionRef, settings: ResumeSettings | None = None
    ) -> SessionRef:
        if settings is not None and settings.mode_id is not None:
            self.validate_resume_mode(settings.mode_id)
        record = json.loads(self._path(ref.session_id).read_text(encoding="utf-8"))
        if ref.session_id in self._servers:
            return ref
        owner_pid = record.get("owner_pid")
        if _owner_is_alive(
            owner_pid, record.get("owner_identity"), self._identity_reader
        ):
            if owner_pid != os.getpid() or ref.session_id not in self._passwords:
                raise RuntimeError("OpenCode server is owned by another live runner")
            server = self._server_record(record, self._passwords[ref.session_id])
        else:
            pid = record.get("pid")
            actual = self._identity_reader(pid) if isinstance(pid, int) else None
            if _recorded_process_matches(record, actual):
                await _terminate_process_group(pid)
            server = await self._restart_server(ref.session_id, record)
        await self._wait_ready(server)
        await self._request(server, "GET", f"/api/session/{record['session_id']}")
        self._servers[ref.session_id] = server
        self._queues[ref.session_id] = asyncio.Queue()
        self._pending.setdefault(ref.session_id, {})
        self._resolved.setdefault(ref.session_id, set())
        self._settled.setdefault(ref.session_id, asyncio.Event()).set()
        self._streams[ref.session_id] = asyncio.create_task(self._events(ref, server))
        try:
            await asyncio.wait_for(server["connected"].wait(), 10)
        except TimeoutError as exc:
            await self.stop(ref)
            raise RuntimeError("OpenCode SSE subscription did not reconnect") from exc
        return ref

    def _server_record(self, record: dict[str, Any], password: str) -> dict[str, Any]:
        return {
            "base": f"http://127.0.0.1:{record['port']}",
            "password": password,
            "session_id": record["session_id"],
            "pid": record.get("pid"),
            "connected": asyncio.Event(),
            "stop": asyncio.Event(),
        }

    async def _restart_server(self, sid: str, record: dict[str, Any]) -> dict[str, Any]:
        executable = record.get("executable") or self.executable
        if not executable:
            raise RuntimeError("opencode executable not found on PATH")
        password = secrets.token_urlsafe(32)
        env = dict(os.environ)
        env.update(
            {
                "OPENCODE_PASSWORD": password,
                "VARDE_AGENT_ID": record.get("agent_id") or record["workspace_id"],
                "VARDE_HARNESS": "opencode-http",
            }
        )
        process = await asyncio.create_subprocess_exec(
            executable,
            "serve",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(record["port"]),
            cwd=record["cwd"],
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        server = self._server_record(record, password)
        server.update(process=process, pid=process.pid)
        identity = self._identity_reader(process.pid)
        if identity is None:
            await _terminate_process_group(process.pid)
            await process.wait()
            raise RuntimeError("OpenCode process identity could not be inspected")
        self._passwords[sid] = password
        self._stderr_readers[sid] = asyncio.create_task(self._drain_stderr(process))
        record.update(
            pid=process.pid,
            identity=list(identity),
            command=identity[1],
            owner_pid=os.getpid(),
            owner_identity=_identity_json(self._identity_reader(os.getpid())),
            executable=executable,
        )
        self._write_record(self._path(sid), record)
        return server

    async def usage(self, ref: SessionRef) -> dict[str, Any] | None:
        server = self._servers.get(ref.session_id)
        if not server or not server.get("session_id"):
            return None
        result = await self._request(
            server, "GET", f"/api/session/{server['session_id']}"
        )
        data = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data, dict) or not isinstance(data.get("tokens"), dict):
            return None
        return {
            "source": "opencode",
            "tokens": data["tokens"],
            "cost": data.get("cost"),
        }

    async def close(self) -> None:
        """Release in-process readers; servers keep running for recover_orphans."""
        tasks = [*self._streams.values(), *self._stderr_readers.values()]
        for server in self._servers.values():
            server["stop"].set()
            response = server.get("response")
            if response:
                response.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._streams.clear()
        self._stderr_readers.clear()

    async def stop(self, ref: SessionRef) -> None:
        sid = ref.session_id
        task = self._streams.pop(ref.session_id, None)
        server = self._servers.pop(ref.session_id, None)
        if server:
            server["stop"].set()
            response = server.get("response")
            if response:
                response.close()
            pid = server.get("pid")
            if isinstance(pid, int):
                await _terminate_process_group(pid)
            process = server.get("process")
            if process and process.returncode is None:
                await process.wait()
        if task:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(task, 3)
        stderr_task = self._stderr_readers.pop(sid, None)
        if stderr_task:
            if not stderr_task.done():
                stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)
        self._passwords.pop(sid, None)
        self._path(sid).unlink(missing_ok=True)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _identity_json(identity: tuple[str, str] | None) -> list[str] | None:
    return list(identity) if identity else None


def _owner_is_alive(
    pid: Any,
    recorded_identity: Any,
    identity_reader: Callable[[int], tuple[str, str] | None],
) -> bool:
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    actual = identity_reader(pid)
    if actual is None:
        return True
    return list(actual) == recorded_identity


def _recorded_process_matches(
    record: dict[str, Any], actual: tuple[str, str] | None
) -> bool:
    identity = record.get("identity")
    command = record.get("command")
    return (
        actual is not None
        and isinstance(identity, list)
        and len(identity) == 2
        and isinstance(command, str)
        and list(actual) == [*identity[:1], command]
    )


async def _terminate_process_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGTERM)
    if not await wait_for_group_exit(pid, 5, _process_group_alive, poll_interval=0.05):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)
        await wait_for_group_exit(pid, 2, _process_group_alive, poll_interval=0.05)
    if _process_group_alive(pid):
        raise RuntimeError(f"OpenCode process group {pid} did not exit")


def _process_group_alive(pid: int) -> bool:
    return process_group_exists(pid)


def _process_identity(pid: int) -> tuple[str, str] | None:
    identity = inspect_process(
        pid,
        "OpenCode",
        executable="/bin/ps",
        output_args=("lstart=", "-o", "command="),
        on_error="none",
        timeout=None,
    )
    return (identity.start_time, identity.command) if identity else None


def _version(text: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:\+[0-9A-Za-z.-]+)?", text):
        raise ValueError(f"unsupported OpenCode version format: {text}")
    return tuple(int(part) for part in text.split("+")[0].split("."))  # type: ignore[return-value]


def _has_route(paths: dict[str, Any], method: str, path: str) -> bool:
    return path in paths and method.lower() in paths[path]

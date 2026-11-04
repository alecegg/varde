"""Shared process identity and durable state helpers for CLI adapters.

Identity inspection has sync and async entry points to preserve adapter behavior:
OpenCode uses synchronous ``/bin/ps`` without a timeout and treats errors as
missing identity, while Pi uses asyncio with a two-second timeout and raises on
inspection errors.
"""

from __future__ import annotations

import asyncio
import errno
import json
import os
import shutil
import signal
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from varde_runner.events import RunnerEvent
from varde_runner.plugins import SessionSpec


@dataclass(frozen=True)
class ProcessIdentity:
    start_time: str
    command: str


def inspect_process(
    pid: int,
    product: str,
    *,
    executable: str | None = None,
    output_args: tuple[str, ...] = ("lstart=,command=",),
    on_error: Literal["raise", "none"] = "raise",
    timeout: float | None = 2,
) -> ProcessIdentity | None:
    ps = executable or shutil.which("ps")
    if ps is None:
        raise FileNotFoundError(f"ps is required for {product} orphan recovery")
    try:
        result = subprocess.run(  # noqa: S603 - fixed ps executable and integer PID.
            [ps, "-p", str(pid), "-o", *output_args],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except OSError, subprocess.SubprocessError:
        if on_error == "none":
            return None
        raise
    if result.returncode:
        if result.stderr.strip():
            if on_error == "none":
                return None
            raise RuntimeError(f"ps could not inspect the {product} process")
        return None
    fields = result.stdout.strip().split(maxsplit=5)
    if len(fields) != 6:
        if on_error == "none":
            return None
        raise ValueError(f"ps returned an invalid {product} process identity")
    return ProcessIdentity(" ".join(fields[:5]), fields[5])


async def inspect_process_async(pid: int, product: str) -> ProcessIdentity | None:
    """Inspect a process using asyncio to preserve Pi's async timeout behavior."""
    ps = shutil.which("ps")
    if ps is None:
        raise FileNotFoundError(f"ps is required for {product} orphan recovery")
    process = await asyncio.create_subprocess_exec(
        ps,
        "-p",
        str(pid),
        "-o",
        "lstart=,command=",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), 2)
    except TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError(f"ps timed out while inspecting {product} process") from None
    if process.returncode:
        if stderr.strip():
            raise RuntimeError(f"ps could not inspect {product} process")
        return None
    fields = stdout.decode(errors="replace").strip().split(maxsplit=5)
    if len(fields) != 6:
        raise ValueError(f"ps returned an invalid {product} process identity")
    return ProcessIdentity(" ".join(fields[:5]), fields[5])


def process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_record(
    value: dict[str, Any],
) -> tuple[int | None, int | None, list[str], str | None]:
    pid = value.get("pid")
    process_group = value.get("process_group")
    command = value.get("command")
    started_at = value.get("started_at")
    valid = (
        isinstance(pid, int)
        and not isinstance(pid, bool)
        and isinstance(process_group, int)
        and process_group == pid
        and isinstance(command, list)
        and all(isinstance(item, str) for item in command)
        and isinstance(started_at, str)
    )
    if not valid:
        return None, process_group if isinstance(process_group, int) else None, [], None
    return cast(
        "tuple[int, int, list[str], str]", (pid, process_group, command, started_at)
    )


def persist_spec(path: Path, spec: SessionSpec) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = {
        "provider": spec.provider,
        "model": spec.model,
        "workspace_id": spec.workspace_id,
        "cwd": spec.cwd,
        "reasoning_effort": spec.reasoning_effort,
        "mode_id": spec.mode_id,
        "prompt": spec.prompt,
        "profile": spec.profile,
    }
    write_state(path, value)


def spec_path(state_dir: Path, session_id: str, product: str) -> Path:
    try:
        canonical_id = str(uuid.UUID(session_id))
    except ValueError as exc:
        raise RuntimeError(f"invalid {product} session id") from exc
    return state_dir / f"{canonical_id}.json"


def mark_unavailable(
    state_dir: Path,
    session_id: str,
    value: dict[str, Any],
    reason: str,
    product: str,
) -> None:
    value["recovery_status"] = "unavailable"
    value["recovery_reason"] = reason
    write_state(spec_path(state_dir, session_id, product), value)


def clear_process_record(
    state_dir: Path, session_id: str, pid: int | None = None
) -> None:
    try:
        path = spec_path(state_dir, session_id, "process")
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError, TypeError, RuntimeError:
        return
    if pid is not None and value.get("pid") != pid:
        return
    for field in ("pid", "process_group", "command", "started_at"):
        value.pop(field, None)
    write_state(path, value)


def write_state(path: Path, value: dict[str, Any]) -> None:
    temp_path = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


async def wait_for_group_exit(
    process_group: int,
    timeout: float,
    exists: Callable[[int], bool],
    *,
    poll_interval: float = 0.02,
) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while exists(process_group):
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(poll_interval)
    return True


def redact_tool_input(event: RunnerEvent) -> RunnerEvent:
    payload = dict(event.payload)
    raw = payload.get("raw")
    if isinstance(raw, dict):
        raw = dict(raw)
        raw.pop("input", None)
        payload["raw"] = raw
    return RunnerEvent(
        kind=event.kind,
        session_id=event.session_id,
        payload=payload,
        provider_id=event.provider_id,
        timestamp=event.timestamp,
        raw_event_ref=event.raw_event_ref,
    )


def without_payload_field(event: RunnerEvent, field: str) -> RunnerEvent:
    payload = dict(event.payload)
    payload.pop(field, None)
    return RunnerEvent(
        kind=event.kind,
        session_id=event.session_id,
        payload=payload,
        provider_id=event.provider_id,
        timestamp=event.timestamp,
        raw_event_ref=event.raw_event_ref,
    )


async def stop_orphan(  # noqa: PLR0911, PLR0913 - injected recovery seams and fail-closed exits.
    session_id: str,
    *,
    path: Path,
    product: str,
    inspect: Callable[[int, list[str]], ProcessIdentity | None],
    signal_group: Callable[[int, int], None],
    group_exists: Callable[[int], bool],
    timeout: float,
    mark_unavailable: Callable[[str, dict[str, Any], str], None],
    clear_record: Callable[[str, int | None], None],
) -> bool:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError, TypeError:
        return True
    if value.get("recovery_status") == "unavailable":
        return False
    pid, process_group, command, started_at = _process_record(value)
    if pid is None:
        if any(key in value for key in ("pid", "process_group", "command")):
            mark_unavailable(session_id, value, "persisted process record is invalid")
            return False
        return True
    process_group = cast("int", process_group)
    command = cast("list[str]", command)
    started_at = cast("str", started_at)
    try:
        identity = inspect(pid, command)
    except OSError, ValueError, subprocess.SubprocessError:
        mark_unavailable(session_id, value, f"{product} process could not be inspected")
        return False
    if identity is None:
        clear_record(session_id, pid)
        return True
    command_matches = all(argument in identity.command for argument in command)
    if identity.start_time != started_at or not command_matches:
        mark_unavailable(session_id, value, "persisted process identity changed")
        return False
    try:
        signal_group(process_group, signal.SIGTERM)
    except ProcessLookupError:
        clear_record(session_id, pid)
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            clear_record(session_id, pid)
            return True
        mark_unavailable(session_id, value, "orphan process could not be stopped")
        return False
    if await wait_for_group_exit(process_group, timeout, group_exists):
        clear_record(session_id, pid)
        return True
    try:
        signal_group(process_group, signal.SIGKILL)
    except OSError as exc:
        if exc.errno != errno.ESRCH:
            mark_unavailable(session_id, value, "orphan process could not be killed")
            return False
    if await wait_for_group_exit(process_group, timeout, group_exists):
        clear_record(session_id, pid)
        return True
    mark_unavailable(session_id, value, "orphan process group did not exit")
    return False

"""Deadline-bound subprocess execution used by learn evals."""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunRequest:
    program: str
    args: Sequence[str]
    cwd: Path | None
    env: Mapping[str, str]
    stdin: bytes
    stdout_path: Path
    stderr_path: Path
    timeout: float


@dataclass(frozen=True)
class ExitResult:
    code: int

    def as_shell_code(self) -> int:
        return 128 + abs(self.code) if self.code < 0 else self.code


@dataclass(frozen=True)
class RunOutcome:
    result: ExitResult | None
    timed_out: bool = False


def run_with_timeout(request: RunRequest) -> RunOutcome:
    request.stdout_path.parent.mkdir(parents=True, exist_ok=True)
    request.stderr_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with (
            request.stdout_path.open("wb") as stdout,
            request.stderr_path.open("wb") as stderr,
        ):
            child = subprocess.Popen(  # noqa: S603 - Launches the configured child process for the process wrapper.
                [request.program, *request.args],
                cwd=request.cwd,
                env={**os.environ, **request.env},
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            communicate_errors: list[BaseException] = []

            def communicate() -> None:
                try:
                    child.communicate(request.stdin)
                except BaseException as error:  # noqa: BLE001 - relay worker exceptions
                    communicate_errors.append(error)

            communication = threading.Thread(target=communicate)
            communication.start()
            try:
                communication.join(request.timeout)
            except BaseException:
                _kill_group(child.pid)
                child.wait()
                communication.join()
                raise
            if communication.is_alive():
                _kill_group(child.pid)
                child.wait()
                communication.join()
                return RunOutcome(None, timed_out=True)
            if communicate_errors:
                _kill_group(child.pid)
                child.wait()
                raise communicate_errors[0]
            _kill_group(child.pid)
            return RunOutcome(ExitResult(child.returncode or 0))
    except OSError as error:
        raise RuntimeError(f"failed to launch {request.program}: {error}") from error


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError, PermissionError:
        return
    deadline = time.monotonic() + 0.25
    while time.monotonic() < deadline:
        try:
            os.killpg(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        time.sleep(0.02)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(pid, signal.SIGKILL)

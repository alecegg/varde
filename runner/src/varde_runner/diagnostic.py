"""Guidance for sessions that produce no startup output."""

from __future__ import annotations

import sys
from typing import Any


def startup_diagnostic(
    spec: Any,
    platform: str,
    elapsed_s: float,
    runner_executable: str,
    interpreter: str,
) -> str:
    """Describe a silent child and list practical ways to resolve the hang."""
    lines = [
        f"The child produced no output after {elapsed_s:.1f}s.",
        (
            "An OS folder-access prompt may be pending and cannot be answered "
            "under a service."
        ),
    ]
    if platform == "darwin":
        lines.append(
            "On macOS, check Files and Folders or Full Disk Access in "
            "Privacy & Security."
        )
    lines.extend(
        (
            (
                f"Add the runner executable {runner_executable!r} and "
                f"interpreter {interpreter!r} to the OS privacy settings."
            ),
            "Start the runner once from a terminal and answer any prompt.",
            "Start the runner from a login session that already has access.",
            (
                "Otherwise change the harness configuration or session cwd "
                f"{getattr(spec, 'cwd', '')!r}."
            ),
        )
    )
    return "\n".join(lines)


def append_startup_diagnostic(
    error: BaseException,
    spec: Any,
    elapsed_s: float,
    runner_executable: str,
    interpreter: str,
) -> None:
    """Append guidance without changing the error class or structured args."""
    diagnostic = startup_diagnostic(
        spec, sys.platform, elapsed_s, runner_executable, interpreter
    )
    args = error.args
    if isinstance(error, OSError) and error.errno is not None:
        error.strerror = f"{error.strerror or ''}\n{diagnostic}"
        return
    if args and isinstance(args[0], dict):
        details = dict(args[0])
        key = "error" if isinstance(details.get("error"), dict) else None
        target = dict(details[key]) if key else details
        message_key = "message" if "message" in target else None
        if message_key:
            target[message_key] = f"{target[message_key]}\n{diagnostic}"
        else:
            target["message"] = diagnostic
        if key:
            details[key] = target
        else:
            details = target
        error.args = (details, *args[1:])
        return
    error.args = ((str(args[0]) if args else str(error)) + f"\n{diagnostic}", *args[1:])


class StartupTimeout(RuntimeError):
    """A plugin handshake that gave up waiting for its child."""


def startup_timeout_error(error: BaseException) -> bool:
    """Return whether an error is a timeout from a startup handshake."""
    return isinstance(error, TimeoutError | StartupTimeout)

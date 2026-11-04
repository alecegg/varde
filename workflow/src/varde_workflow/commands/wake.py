"""Run the configured hook command for a plan watch event."""

from __future__ import annotations

import os
import subprocess
import sys
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from varde_workflow.inbox import MAX_TEXT_CHARS


@dataclass
class WakeRunner:
    argv: list[str]
    timeout: float
    max_failures: int
    failures: int = 0
    disabled: bool = False

    @classmethod
    def load(cls) -> WakeRunner:
        from varde_learn.knowledge.memory_config import load_config

        config = load_config().orchestration
        argv, command_error = config.wake_command()
        if command_error:
            print(
                (
                    "varde plan watch: orchestration.wake_command ignored "
                    f"({command_error}); using an empty command"
                ),
                file=sys.stderr,
            )
        timeout, timeout_error = config.wake_timeout_seconds()
        if timeout_error:
            print(
                (
                    "varde plan watch: orchestration.wake_timeout_seconds ignored "
                    f"({timeout_error}); using {timeout}"
                ),
                file=sys.stderr,
            )
        max_failures, failures_error = config.wake_max_failures()
        if failures_error:
            print(
                (
                    "varde plan watch: orchestration.wake_max_failures ignored "
                    f"({failures_error}); using {max_failures}"
                ),
                file=sys.stderr,
            )
        return cls(argv, timeout, max_failures)

    @classmethod
    def empty(cls) -> WakeRunner:
        return cls([], 0, 0)

    def run(self, event: object) -> str | None:
        if not self.argv or self.disabled:
            return None
        try:
            _run_command(self.argv, self.timeout, event)
        except RuntimeError as exc:
            self.failures += 1
            message = f"wake failed: {exc}"
            if self.failures >= self.max_failures:
                self.disabled = True
                return f"{message}; wake is disabled until restart"
            return message
        self.failures = 0
        return None


def _clean(value: str, limit: int) -> str:
    return "".join(
        character for character in value if unicodedata.category(character) != "Cc"
    )[:limit]


def _run_command(argv: list[str], timeout: float, event: object) -> None:
    kind = getattr(event, "kind", "")
    kind = getattr(kind, "value", kind)
    kind = {
        "Stale": "stale",
        "Blocked": "blocked",
        "NeedsDecision": "needs-decision",
        "MergeReady": "merge-ready",
        "Finished": "finished",
    }.get(str(kind), str(kind))
    plan = str(getattr(event, "plan", ""))
    owner = getattr(event, "owner", None) or ""
    line_fn = getattr(event, "line", None)
    line = cast("Callable[[], str]", line_fn)() if callable(line_fn) else str(event)
    environment = {
        "VARDE_WAKE_EVENT": kind,
        "VARDE_WAKE_PLAN": _clean(plan, MAX_TEXT_CHARS),
        "VARDE_WAKE_OWNER": _clean(owner, MAX_TEXT_CHARS),
        "VARDE_WAKE_TEXT": _clean(line, MAX_TEXT_CHARS),
    }
    try:
        process = subprocess.Popen(  # noqa: S603 - Starts the explicitly selected harness command with argv and no shell.
            argv,
            env={**os.environ, **environment},
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise RuntimeError(f"could not start command: {exc}") from exc
    try:
        status = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.wait()
        raise RuntimeError(f"command timed out after {int(timeout)}s") from exc
    if status:
        raise RuntimeError(f"command exited with exit status {status}")

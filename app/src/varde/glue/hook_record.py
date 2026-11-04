"""Record guardrail firings without loading the Varde package graph."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, TypedDict, cast

# Copy of varde_learn.loop.calls.SESSION_VARS; kept local so hooks skip the package
# graph. app/tests/test_hook_record.py checks the two stay equal.
SESSION_VARS = (
    "CLAUDE_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_THREAD_ID",
    "VARDE_TOZ_SESSION",
)


class CallRow(TypedDict):
    ts: str
    command: str
    status: str
    duration_s: float
    session: str | None
    guardrail: NotRequired[str]


def build_row(guardrail_id: str, *, blocked: bool = False) -> CallRow:
    """Build the call-log row for one guardrail firing."""
    session = next(
        (os.environ[name] for name in SESSION_VARS if os.environ.get(name)),
        None,
    )
    return {
        "ts": datetime.now(UTC).isoformat(),
        "command": f"hook {guardrail_id}",
        "status": "blocked" if blocked else "success",
        "duration_s": 0.0,
        "session": session,
        "guardrail": guardrail_id,
    }


def config_dir() -> Path:
    """Resolve the Varde config directory from the standard environment."""
    configured = os.environ.get("VARDE_CONFIG_DIR")
    if configured:
        return Path(configured)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "varde"
    home = os.environ.get("HOME")
    if home:
        return Path(home) / ".config" / "varde"
    try:
        return Path.home() / ".config" / "varde"
    except RuntimeError:
        return Path(".config") / "varde"


def resolve_store_dir() -> Path:
    """Resolve the configured global learn store."""
    from varde_learn.loop.store.paths import resolve_store_dir as resolve_learn_store

    return resolve_learn_store(config_dir=config_dir())


def record_firing(guardrail_id: str, *, blocked: bool = False) -> bool:
    """Record a firing through the learn calls store; errors never escape."""
    try:
        from varde_learn.loop.calls import CallRow as LearnCallRow
        from varde_learn.loop.calls import append_call

        row = cast("LearnCallRow", build_row(guardrail_id, blocked=blocked))
        return append_call(row, resolve_store_dir())
    except Exception:  # noqa: BLE001 - recording must not change hook behavior.
        return False

"""Runner plugin types."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

_INHERITED_IDENTITY_ENV = {
    "VARDE_ADDRESS",
    "VARDE_AGENT_ID",
    "VARDE_HARNESS",
    "VARDE_RUNNER_ENDPOINT",
}


def child_environment(overlay: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy the environment without ambient Paseo or Varde identity values.

    ``overlay`` (``SessionSpec.env``) is applied last. A restricted-profile session
    does not use this function: it gets an allowlisted environment instead.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("PASEO_") and key not in _INHERITED_IDENTITY_ENV
    }
    removed = sorted(set(os.environ) - set(env))
    logging.getLogger(__name__).info("native_child_env_scrubbed keys=%s", removed)
    env.update(overlay or {})
    return env


@dataclass(frozen=True, slots=True)
class RunnerCapabilities:
    resume: bool = False
    guard_read_only: bool = False
    permission_commands: bool = False
    usage: bool = False
    idle_status: bool = False
    external_wake: bool = False
    persistent_process: bool = False
    steer: bool = False
    interrupt: bool = False
    respond: bool = False
    restricted_profile: bool = False


@dataclass(frozen=True, slots=True)
class SessionSpec:
    provider: str
    model: str
    workspace_id: str
    cwd: str
    prompt: str = ""
    reasoning_effort: str | None = None
    mode_id: str | None = None
    agent_id: str | None = None
    runner_harness: str | None = None
    role: str = "builder"
    # Restricted-profile name; persisted so a restart cannot downgrade the session.
    profile: str | None = None
    # Gateway identity of the bot-rooted launcher, if any; drives the taint token.
    launched_by: str | None = None
    # Env overlay (bot or taint token). Never persisted, never shown in repr.
    env: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class SessionSettings:
    model: str
    reasoning_effort: str | None = None
    mode_id: str | None = None


@dataclass(frozen=True, slots=True)
class SessionRef:
    provider: str
    session_id: str


__all__ = [
    "RunnerCapabilities",
    "SessionRef",
    "SessionSettings",
    "SessionSpec",
    "child_environment",
]

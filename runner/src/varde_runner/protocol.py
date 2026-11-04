"""Stable adapter contract and capability checks."""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol, cast

from varde_runner.config import Model
from varde_runner.events import RunnerEvent
from varde_runner.plugins import (
    RunnerCapabilities,
    SessionRef,
    SessionSettings,
    SessionSpec,
)


class UnsupportedCapability(RuntimeError):
    """Raised when an adapter operation is not advertised as supported."""


def plugin_is_provider_limit_error(plugin: object, exc: BaseException) -> bool:
    """Ask a plugin whether an error represents its provider's usage limit."""
    classifier = getattr(plugin, "is_provider_limit_error", None)
    return bool(classifier(exc)) if callable(classifier) else False


@dataclass(frozen=True, slots=True)
class ResumeSettings:
    """Session settings a resume may change; ``None`` fields keep the stored value."""

    mode_id: str | None = None


def accepts_settings(plugin: object) -> bool:
    return "settings" in inspect.signature(plugin.resume).parameters  # type: ignore[attr-defined]


async def resume(
    plugin: object, ref: SessionRef, settings: ResumeSettings | None = None
) -> SessionRef:
    plugin = cast("RunnerPlugin", plugin)
    if not plugin.capabilities.resume:
        raise UnsupportedCapability("resume is not supported by this plugin")
    if settings is None:
        return await plugin.resume(ref)
    if not accepts_settings(plugin):
        raise UnsupportedCapability("changing settings is not supported by this plugin")
    return await plugin.resume(ref, settings)


class RunnerPlugin(Protocol):
    capabilities: RunnerCapabilities

    def session_settings(self, model: Model) -> SessionSettings: ...
    def is_provider_limit_error(self, exc: BaseException) -> bool: ...
    async def start(self, spec: SessionSpec) -> SessionRef: ...
    async def resume(
        self, ref: SessionRef, settings: ResumeSettings | None = None
    ) -> SessionRef: ...
    async def send(self, ref: SessionRef, prompt: str) -> None: ...
    def events(self, ref: SessionRef) -> AsyncGenerator[RunnerEvent]: ...
    async def respond_permission(
        self, ref: SessionRef, request_id: str, decision: str
    ) -> None: ...
    async def stop(self, ref: SessionRef) -> None: ...
    async def close(self) -> None: ...


class InterruptiblePlugin(RunnerPlugin, Protocol):
    async def interrupt(self, ref: SessionRef) -> None: ...

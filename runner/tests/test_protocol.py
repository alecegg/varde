from __future__ import annotations

import asyncio

import pytest
from varde_runner.events import RunnerEvent
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.protocol import UnsupportedCapability, resume


def test_event_kinds_include_permission_lifecycle_separately() -> None:
    requested = RunnerEvent(
        kind="permission_requested", session_id="s", payload={"id": "p"}
    )
    resolved = RunnerEvent(
        kind="permission_resolved", session_id="s", payload={"id": "p"}
    )
    assert requested.kind != resolved.kind


def test_resume_rejects_unsupported_capability() -> None:
    class Plugin:
        capabilities = RunnerCapabilities(resume=False)

        async def start(self, spec: SessionSpec) -> SessionRef:
            raise AssertionError

        async def resume(self, ref: SessionRef) -> SessionRef:
            raise AssertionError("unsupported resume reached adapter")

        async def send(self, ref: SessionRef, prompt: str) -> None:
            raise AssertionError

        async def events(self, ref: SessionRef):
            if False:
                yield RunnerEvent(kind="status", session_id=ref.session_id)

        async def respond_permission(
            self, ref: SessionRef, request_id: str, decision: str
        ) -> None:
            raise AssertionError

        async def stop(self, ref: SessionRef) -> None:
            raise AssertionError

        async def close(self) -> None:
            raise AssertionError

    with pytest.raises(UnsupportedCapability):
        asyncio.run(resume(Plugin(), SessionRef("paseo", "agent")))


def test_session_spec_and_ref_are_plain_data() -> None:
    spec = SessionSpec(
        provider="codex",
        model="gpt-6-luna",
        workspace_id="w",
        cwd="/tmp",  # noqa: S108 - Protocol fixture includes an arbitrary absolute cwd.
    )
    ref = SessionRef(provider="paseo", session_id="agent")
    assert spec.workspace_id == "w"
    assert ref.session_id == "agent"

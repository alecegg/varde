from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from varde_runner.config import Model
from varde_runner.plugins import SessionRef, SessionSpec
from varde_runner.plugins.paseo import PaseoPlugin, _normalize

PASEO_CLI = Path("/Applications/Paseo.app/Contents/Resources/bin/paseo")


@pytest.mark.parametrize(
    ("harness", "mode", "mode_id"),
    [
        ("codex-app-server", "auto", "auto"),
        ("codex-app-server", "workspace-write", "auto"),
        ("codex-app-server", "full-access", "full-access"),
        ("codex-app-server", "danger-full-access", "full-access"),
        ("pi", "auto", "auto"),
        ("pi", "read-only", "read-only"),
        ("pi", "workspace-write", "workspace-write"),
        ("pi", "full-access", "full-access"),
        ("pi", "danger-full-access", "danger-full-access"),
        ("claude-sdk", "auto", "auto"),
        ("claude-sdk", "read-only", "plan"),
        ("claude-sdk", "workspace-write", "acceptEdits"),
        ("claude-sdk", "full-access", "bypassPermissions"),
        ("claude-sdk", "danger-full-access", "bypassPermissions"),
    ],
)
def test_paseo_session_settings_keep_harness_mode_parity(harness, mode, mode_id):
    settings = PaseoPlugin.session_settings(
        Model(harness, "gpt-6-luna", "medium", mode)
    )

    assert settings.model == "gpt-6-luna"
    assert settings.reasoning_effort == "medium"
    assert settings.mode_id == mode_id


def test_paseo_session_settings_reject_invalid_mode_and_sol_model():
    with pytest.raises(ValueError, match="unsupported runner mode"):
        PaseoPlugin.session_settings(Model("pi", "gpt-6-luna", "medium", "unsafe"))
    with pytest.raises(ValueError, match="no Paseo equivalent"):
        PaseoPlugin.session_settings(
            Model("codex-app-server", "gpt-6-luna", "medium", "read-only")
        )
    with pytest.raises(ValueError, match="sol models are prohibited"):
        PaseoPlugin.session_settings(
            Model("pi", "gpt-6-sol", "medium", "workspace-write")
        )


def test_paseo_capabilities_and_normalized_provider_id():
    assert PaseoPlugin.capabilities.respond is True
    assert PaseoPlugin.capabilities.interrupt is False
    event = _normalize("session", {"event": "status", "payload": {"status": "idle"}})
    assert event.provider_id == "paseo"


def test_sidecar_pins_the_verified_public_paseo_client(
    sidecar_package: dict[str, object],
) -> None:
    dependencies = sidecar_package["dependencies"]
    assert dependencies == {"@getpaseo/client": "0.12.0"}


def test_real_paseo_daemon_contract() -> None:
    if not PASEO_CLI.is_file():
        pytest.skip(f"Paseo CLI not found at {PASEO_CLI}")
    if os.environ.get("VARDE_RUNNER_PASEO_LIVE") != "1":
        pytest.skip("set VARDE_RUNNER_PASEO_LIVE=1 to use the real Paseo daemon")
    workspace_id = os.environ.get("VARDE_RUNNER_PASEO_WORKSPACE_ID")
    workspace_cwd = os.environ.get("VARDE_RUNNER_PASEO_CWD")
    if not workspace_id or not workspace_cwd:
        pytest.skip(
            "set VARDE_RUNNER_PASEO_WORKSPACE_ID and VARDE_RUNNER_PASEO_CWD "
            "to use the real Paseo daemon"
        )
    asyncio.run(_exercise_adapter(workspace_id, Path(workspace_cwd), _daemon_url()))


def _daemon_url() -> str:
    result = subprocess.run(  # noqa: S603 - Test runs a controlled local command to verify adapter behavior.
        [str(PASEO_CLI), "daemon", "status", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    status = json.loads(result.stdout)
    if status.get("localDaemon") != "running":
        raise AssertionError(
            f"Paseo daemon is not running: {status.get('localDaemon')}"
        )
    listen = status.get("listen")
    if not isinstance(listen, str) or ":" not in listen:
        raise AssertionError(f"Paseo daemon has no TCP listen address: {listen}")
    return f"ws://{listen}/ws"


async def _exercise_adapter(workspace_id: str, workspace_dir: Path, url: str) -> None:
    plugin = PaseoPlugin(Path("/tmp") / f"vr-{uuid.uuid4().hex}.sock", url)  # noqa: S108 - Unix socket fixture uses a short path for platform limits.
    ref = None
    stream = None
    prompt = (
        "Run the shell command `curl -sS https://example.com -o /dev/null` "
        "and report the exit code. Do not run any other command."
    )
    try:
        ref = await plugin.start(
            SessionSpec(
                provider="codex",
                model="gpt-6-luna",
                reasoning_effort="low",
                workspace_id=workspace_id,
                cwd=str(workspace_dir),
                prompt=prompt,
                mode_id="auto",
            )
        )
        initial_status = await plugin._request("inspect", session_id=ref.session_id)
        assert initial_status["current_mode_id"] == "auto", initial_status
        stream = plugin.events(ref)
        try:
            first_events = await _events_until(
                stream,
                lambda events: any(
                    event.kind in {"permission_requested", "error"} for event in events
                ),
                timeout=90,
            )
        except TimeoutError as exc:
            state = await plugin._request("inspect", session_id=ref.session_id)
            pytest.fail(
                f"Permission event did not arrive: {exc}; daemon inspect={state}"
            )
        if not any(event.kind == "permission_requested" for event in first_events):
            state = await plugin._request("inspect", session_id=ref.session_id)
            pytest.fail(
                f"No permission event; events={first_events}; daemon inspect={state}"
            )
        assert any(
            event.kind == "status" and event.payload["status"] == "running"
            for event in first_events
        ), first_events
        permission = next(
            event for event in first_events if event.kind == "permission_requested"
        )
        assert permission.kind != "status"
        state = await plugin._request("inspect", session_id=ref.session_id)
        assert state["current_mode_id"] == "auto", state
        assert any(
            pending.get("requestId") == permission.payload["request_id"]
            for pending in state["pending_permissions"]
        ), state
        await plugin.respond_permission(ref, permission.payload["request_id"], "deny")
        after_response = await _events_until(
            stream,
            lambda events: (
                any(event.kind == "permission_resolved" for event in events)
                and any(
                    event.kind == "status" and event.payload["status"] == "idle"
                    for event in events
                )
            ),
            timeout=60,
            prior=first_events,
        )
        assert any(event.kind == "permission_resolved" for event in after_response)
        await stream.aclose()
        stream = None
        process = plugin._process
        assert process is not None
        process.kill()
        await asyncio.wait_for(process.wait(), timeout=10)
        queue = plugin._events[ref.session_id]
        while not queue.empty():
            queue.get_nowait()
        await plugin.resume(ref)
        stream = plugin.events(ref)
        reconnected = await asyncio.wait_for(anext(stream), timeout=30)
        assert reconnected.kind == "status", reconnected
        await plugin.send(
            ref, "Respond with only the word reconnected; do not use tools."
        )
        resumed_events = await _events_until(
            stream,
            lambda events: (
                any(event.kind == "text" for event in events)
                and any(
                    event.kind == "status" and event.payload["status"] == "idle"
                    for event in events
                )
            ),
            timeout=90,
            prior=[reconnected],
        )
        assert any(event.kind == "text" for event in resumed_events)
    finally:
        if stream:
            await stream.aclose()
        if ref:
            await plugin.stop(ref)
        await plugin.close()


async def _events_until(stream, predicate, timeout: float, prior=None):
    events = list(prior or [])
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate(events):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for Paseo events; received {events}")
        try:
            events.append(await asyncio.wait_for(anext(stream), timeout=remaining))
        except TimeoutError as exc:
            raise TimeoutError(
                f"Timed out waiting for Paseo events; received {events}"
            ) from exc
    return events


def test_normalize_reports_the_original_unsupported_event_kind() -> None:
    from varde_runner.plugins.paseo import _normalize

    event = _normalize("session", {"event": "unexpected", "payload": {}})

    assert event.kind == "error"
    assert event.payload == {"message": "unsupported Paseo event: unexpected"}


def test_normalize_marks_an_invalid_status_as_error() -> None:
    from varde_runner.plugins.paseo import _normalize

    event = _normalize("session", {"event": "status", "payload": {"status": "waiting"}})

    assert event.kind == "status"
    assert event.payload["status"] == "error"


@pytest.mark.parametrize(
    ("status", "expected_kind"),
    [
        ("running", "tool_intent"),
        ("completed", "tool_result"),
        ("failed", "tool_result"),
        ("canceled", "tool_result"),
    ],
)
def test_normalize_splits_paseo_tool_call_timeline_items(status, expected_kind):
    item = {
        "type": "tool_call",
        "callId": "call-1",
        "status": status,
        "name": "shell",
        "detail": {"type": "shell", "command": "pwd"},
    }
    event = _normalize(
        "session",
        {"event": "tool", "payload": {"item": item}},
    )

    assert event.kind == expected_kind
    assert event.payload["call_id"] == "call-1"
    assert event.payload["tool"] == "shell"
    assert event.payload["phase"] == status
    assert event.payload["raw"] == {"item": item}


def test_normalize_keeps_legacy_tool_without_call_id_or_phase():
    payload = {"item": {"type": "tool_call", "status": "running"}}

    event = _normalize("session", {"event": "tool", "payload": payload})

    assert event.kind == "tool"
    assert event.payload == payload


def test_normalize_maps_paseo_tool_call_without_name():
    payload = {"item": {"type": "tool_call", "callId": "call-1", "status": "running"}}

    event = _normalize("session", {"event": "tool", "payload": payload})

    assert event.kind == "tool_intent"
    assert event.payload["call_id"] == "call-1"
    assert event.payload["tool"] is None
    assert event.payload["phase"] == "running"
    assert event.payload["raw"] == payload


@pytest.mark.parametrize(
    "payload",
    [
        {"item": {"type": "tool_call", "callId": "", "status": "running"}},
        {"item": {"type": "tool_call", "callId": 42, "status": "running"}},
        {"item": {"type": "tool_call", "callId": "call-1", "status": "pending"}},
        {"item": {"type": "other", "callId": "call-1", "status": "running"}},
        None,
    ],
)
def test_normalize_keeps_unrecognized_tool_payload_legacy(payload):
    event = _normalize("session", {"event": "tool", "payload": payload})

    assert event.kind == "tool"
    assert event.payload is payload


def test_start_forwards_mode_and_prompt_to_sidecar() -> None:
    async def exercise() -> dict[str, object]:
        plugin = PaseoPlugin(Path("unused.sock"), "ws://unused")
        request: dict[str, object] = {}

        async def capture(operation: str, **payload: object) -> dict[str, object]:
            request.update(op=operation, **payload)
            return {"session_id": "agent"}

        plugin._request = capture  # type: ignore[method-assign]
        await plugin.start(
            SessionSpec(
                provider="codex",
                model="gpt-6-luna",
                reasoning_effort="low",
                workspace_id="workspace",
                cwd="/workspace",
                prompt="Run curl.",
                mode_id="auto",
            )
        )
        return request

    request = asyncio.run(exercise())
    assert request["mode_id"] == "auto"
    assert request["prompt"] == "Run curl."


def test_events_yields_snapshot_before_unique_buffered_events() -> None:
    async def exercise() -> list[tuple[str, str | None]]:
        plugin = PaseoPlugin(Path("unused.sock"), "ws://unused")
        ref = SessionRef("paseo", "session")
        queue = plugin._event_queue(ref.session_id)
        queue.put_nowait(
            {
                "session_id": ref.session_id,
                "event": "status",
                "payload": {"status": "idle"},
            }
        )
        queue.put_nowait(
            {
                "session_id": ref.session_id,
                "event": "text",
                "payload": {"text": "new"},
                "raw_event_ref": "live-2",
            }
        )

        async def request(operation: str, **payload: object) -> dict[str, object]:
            assert operation == "subscribe"
            return {
                "snapshot": [
                    {
                        "event": "status",
                        "payload": {"status": "idle"},
                        "raw_event_ref": "snapshot-1",
                    }
                ]
            }

        plugin._request = request  # type: ignore[method-assign]
        stream = plugin.events(ref)
        assert queue.maxsize == 1024
        events = [await anext(stream), await anext(stream)]
        await stream.aclose()
        return [(event.kind, event.raw_event_ref) for event in events]

    assert asyncio.run(exercise()) == [("status", "snapshot-1"), ("text", "live-2")]


def test_sidecar_death_fails_pending_request_and_respawns_with_events(
    tmp_path: Path, require_unix_socket
) -> None:
    script = r"""
import json, socket, sys, time
sock_path = sys.argv[1]
for _ in range(5000):
    print("sidecar diagnostic output", file=sys.stderr)
sys.stderr.flush()
connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
connection.connect(sock_path)
reader = connection.makefile("r")
writer = connection.makefile("w")
for line in reader:
    request = json.loads(line)
    op = request["op"]
    session = request.get("session_id", "agent")
    if op == "start":
        writer.write(json.dumps({"id": request["id"], "session_id": "agent"}) + "\n")
        writer.flush()
        writer.write(
            json.dumps(
                {
                    "session_id": "agent",
                    "event": "permission_requested",
                    "payload": {"request_id": "p"},
                }
            )
            + "\n"
        )
        writer.flush()
    elif op == "permission":
        writer.write(json.dumps({"id": request["id"]}) + "\n")
        writer.flush()
        writer.write(
            json.dumps(
                {
                    "session_id": session,
                    "event": "permission_resolved",
                    "payload": {"request_id": "p"},
                }
            )
            + "\n"
        )
        writer.flush()
    elif op == "hold":
        while True:
            time.sleep(1)
    else:
        writer.write(
            json.dumps(
                {"id": request["id"], "session_id": session, "snapshot": []}
            )
            + "\n"
        )
        writer.flush()
        writer.write(
            json.dumps(
                {
                    "session_id": session,
                    "event": "status",
                    "payload": {"status": "idle"},
                    "raw_event_ref": "resumed",
                }
            )
            + "\n"
        )
        writer.flush()
        writer.write("not-json\n")
        writer.flush()
        writer.write(
            json.dumps(
                {
                    "session_id": session,
                    "event": "text",
                    "payload": {"text": "resumed"},
                    "raw_event_ref": "resumed-text",
                }
            )
            + "\n"
        )
        writer.flush()
"""

    async def exercise() -> None:
        plugin = PaseoPlugin(
            Path("/tmp") / f"vr-{uuid.uuid4().hex}.sock",  # noqa: S108 - Unix socket fixture uses a short path for platform limits.
            "ws://unused",
            sidecar_command=(sys.executable, "-u", "-c", script),
        )
        ref = SessionRef("paseo", "agent")
        try:
            await plugin._request("start")
            first_process = plugin._process
            assert first_process is not None
            event_queue = plugin._event_queue("agent")
            permission = await asyncio.wait_for(event_queue.get(), timeout=2)
            assert permission["event"] == "permission_requested"
            await plugin.respond_permission(ref, "p", "deny")
            resolved = await asyncio.wait_for(event_queue.get(), timeout=2)
            assert resolved["event"] == "permission_resolved"

            pending = asyncio.create_task(plugin._request("hold"))
            await asyncio.sleep(0.05)
            first_process.kill()
            await first_process.wait()
            with pytest.raises(RuntimeError, match="disconnected"):
                await asyncio.wait_for(pending, timeout=2)

            await plugin.resume(ref)
            second_process = plugin._process
            assert second_process is not None
            assert second_process.pid != first_process.pid
            stream = plugin.events(ref)
            resumed = [
                await asyncio.wait_for(anext(stream), timeout=2) for _ in range(2)
            ]
            assert [(event.kind, event.raw_event_ref) for event in resumed] == [
                ("status", "resumed"),
                ("text", "resumed-text"),
            ]
            await stream.aclose()
        finally:
            await plugin.close()

    asyncio.run(exercise())

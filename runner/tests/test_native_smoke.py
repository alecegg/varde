from __future__ import annotations

import asyncio
import importlib.util
import os
import socket
import sys
from io import BytesIO
from pathlib import Path
from typing import Any

from fakes.plugin import FakePlugin
from varde_runner.config import adapter_state_root, parse_config
from varde_runner.plugins import SessionRef, SessionSpec

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "native_smoke.py"
_SPEC = importlib.util.spec_from_file_location("native_smoke", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
config_text = _MODULE.config_text
drive = _MODULE.drive


def test_runner_environment_prefers_checkout_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin")
    env = _MODULE.runner_environment(tmp_path, tmp_path, tmp_path)

    assert env["PATH"].split(os.pathsep)[0] == str(
        Path(sys.executable).absolute().parent
    )
    assert _MODULE.runtime_info(env)["varde_executable"] == str(
        Path(sys.executable).absolute().parent / "varde"
    )


def test_adapter_state_root_uses_environment_or_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VARDE_RUNNER_STATE_DIR", str(tmp_path))
    assert adapter_state_root() == tmp_path
    monkeypatch.delenv("VARDE_RUNNER_STATE_DIR")
    assert adapter_state_root() == Path.home() / ".local/share/varde-runner"


class FakeAPI:
    """Exercise the driver's request sequence with the runner's fake adapter."""

    def __init__(self) -> None:
        self.plugin = FakePlugin()
        self.calls: list[str] = []
        self.agent_id = "fake-agent"
        self.ref: SessionRef | None = None
        self.timeout = None
        self.launch_payload = None
        self.event_stream = BytesIO(
            b'data: {"type":"event","kind":"text","payload":{"text":"ok"}}\n'
            b'data: {"type":"event","kind":"status","payload":{"status":"idle"}}\n'
        )

    def request(self, path: str, payload: dict[str, Any] | None = None):
        self.calls.append(path)
        if path == "/api/agents":
            assert payload is not None
            self.launch_payload = payload
            self.ref = asyncio.run(
                self.plugin.start(
                    SessionSpec(
                        "claude-cli",
                        "test-model",
                        payload["workspace"],
                        payload["workspace"],
                        payload["prompt"],
                    )
                )
            )
            asyncio.run(self.plugin.send(self.ref, payload["prompt"]))
            return {"http_status": 201, "body": {"agent_id": self.agent_id}}
        if path.endswith("/interrupt"):
            asyncio.run(self.plugin.interrupt(self._started_ref()))
        elif path.endswith("/resume"):
            asyncio.run(self.plugin.resume(self._started_ref()))
        elif path.endswith("/stop"):
            asyncio.run(self.plugin.stop(self._started_ref()))
        return {"http_status": 200, "body": {}}

    def _started_ref(self) -> SessionRef:
        assert self.ref is not None
        return self.ref

    def events(self, agent_id: str, client: str, timeout: float):
        assert agent_id == self.agent_id
        assert client.startswith("native-smoke-")
        self.timeout = timeout
        return self.event_stream


def test_config_enables_only_selected_adapter_with_default_mode() -> None:
    sections = {
        "claude-cli": "claude_cli",
        "codex-app-server": "codex_app_server",
        "pi-rpc": "pi_rpc",
        "opencode-http": "opencode_http",
    }
    for harness, section in sections.items():
        text = config_text(harness, "builder", "cheap-model", "low")
        assert f"[{section}]\nenabled = true" in text
        assert f'[types.smoke]\nharness = "{harness}"' in text
        if harness == "pi-rpc":
            assert 'mode = "read-only"' in text
        else:
            assert "mode =" not in text
        assert all(
            f"[{other}]" not in text for other in sections.values() if other != section
        )
        parsed = parse_config(text)
        expected_mode = "read-only" if harness == "pi-rpc" else "workspace-write"
        assert parsed.resolve("builder").mode == expected_mode
        assert parsed.resolve("builder").fallback[0].mode == expected_mode


def test_pi_durable_smoke_config_is_enabled_and_workspace_write() -> None:
    text = config_text("pi-durable", "builder", "openai/gpt-4o-mini", "low")
    assert '[pi_durable]\nenabled = true\nprovider = "openai"' in text
    parsed = parse_config(text)
    assert parsed.resolve("builder").mode == "workspace-write"
    assert parsed.resolve("builder").harness == "pi-durable"


def test_driver_calls_lifecycle_once_with_fake_adapter(tmp_path) -> None:
    api = FakeAPI()
    note = drive(api, "claude-cli", "builder", str(tmp_path), "Reply ok")
    assert [step["step"] for step in note["steps"]] == [
        "launch",
        "stream_open",
        "reply",
        "interrupt",
        "resume",
        "stop",
        "archive",
    ]
    assert [step["status"] for step in note["steps"]] == [
        201,
        "completed",
        "completed",
        200,
        200,
        200,
        200,
    ]
    readiness = {"step": "readiness", "status": "ready", "elapsed_seconds": 0.5}
    _MODULE.include_readiness(note, readiness)
    assert note["steps"][0] == readiness
    assert api.plugin.sent == [("remote-1", "Reply ok")]
    assert api.plugin.interrupted == ["remote-1"]
    assert api.plugin.resumed == ["remote-1"]
    assert api.plugin.stopped == ["remote-1"]
    assert api.calls == [
        "/api/agents",
        "/api/agents/fake-agent/interrupt",
        "/api/agents/fake-agent/resume",
        "/api/agents/fake-agent/stop",
        "/api/agents/fake-agent/archive",
    ]
    assert api.timeout == 120
    assert note["events"] == [
        {"kind": "text", "payload_keys": ["text"]},
        {"kind": "status", "payload_keys": ["status"]},
    ]


def test_mail_wake_driver_sends_mail_and_waits_for_new_reply(
    tmp_path, monkeypatch
) -> None:
    api = FakeAPI()
    api.event_stream = BytesIO(
        b'data: {"kind":"text","payload":{"text":"ok"}}\n'
        b'data: {"kind":"status","payload":{"status":"idle"}}\n'
        b'data: {"kind":"text","payload":{"text":"woke"}}\n'
        b'data: {"kind":"status","payload":{"status":"idle"}}\n'
    )
    sent: list[str] = []
    monkeypatch.setattr(
        _MODULE, "send_smoke_mail", lambda working: sent.append(working) or {}
    )

    note = drive(
        api,
        "claude-cli",
        "builder",
        str(tmp_path / "workspace"),
        "Reply ok",
        mail_wake=True,
        mail_working=str(tmp_path / "working"),
    )

    assert "error" not in note
    assert note["initial_reply"] == "ok"
    assert note["wake_reply"] == "woke"
    assert sent == [str(tmp_path / "working")]
    assert api.launch_payload is not None
    assert api.launch_payload["workspace"] == str(tmp_path / "workspace")
    assert api.launch_payload["address"] == {
        "slot": "smoke-orch",
        "plan": "smoke-plan",
    }
    assert [step["step"] for step in note["steps"]] == [
        "launch",
        "stream_open",
        "initial_reply",
        "mail_send",
        "mail_wake_reply",
        "stop",
        "archive",
    ]
    assert api.calls[-2:] == [
        "/api/agents/fake-agent/stop",
        "/api/agents/fake-agent/archive",
    ]


def test_varde_msg_state_reads_from_throwaway_working_dir(monkeypatch, tmp_path):
    import subprocess

    monkeypatch.setattr(_MODULE.shutil, "which", lambda _, **__: "/bin/varde")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "[]", "")

    monkeypatch.setattr(_MODULE.subprocess, "run", run)
    result = _MODULE.varde_msg_state(tmp_path)
    assert result["returncode"] == 0
    assert calls[0][0] == [
        "/bin/varde",
        "msg",
        "read",
        "--as",
        "smoke-orch",
        "--all",
        "--json",
    ]


def test_relay_diagnostics_are_read_and_filter_relay_lines():
    class API:
        def request(self, path, payload=None):
            assert path == "/api/relay"
            return {"enabled": True, "state": "waiting"}

    assert _MODULE.relay_state(API()) == {"enabled": True, "state": "waiting"}
    assert _MODULE.relay_log_lines(
        "INFO relay started: mode=DataRelay\nINFO unrelated"
    ) == ["INFO relay started: mode=DataRelay"]


def test_mail_wake_uses_immediate_needs_user_kind(monkeypatch, tmp_path):
    import subprocess

    monkeypatch.setattr(_MODULE.shutil, "which", lambda _, **__: "/bin/varde")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "sent", "")

    monkeypatch.setattr(_MODULE.subprocess, "run", run)
    _MODULE.send_smoke_mail(str(tmp_path))
    assert calls[0][0][calls[0][0].index("--kind") + 1] == "needs-user"
    assert calls[0][1]["env"]["VARDE_WORKING_DIR"] == str(tmp_path)


def test_reply_events_keep_error_text():
    stream = BytesIO(
        b'data: {"kind":"error","payload":{"message":"provider failed"}}\n'
        b'data: {"kind":"text","payload":{"text":"ok"}}\n'
        b'data: {"kind":"status","payload":{"status":"idle"}}\n'
    )
    events = []

    assert _MODULE.wait_for_reply(stream, 1, events) == "ok"
    assert {
        "kind": "error",
        "payload_keys": ["message"],
        "message": "provider failed",
    } in events


def test_driver_accepts_bounded_error_outcome(tmp_path) -> None:
    api = FakeAPI()
    api.event_stream = BytesIO(
        b'data: {"kind":"error","payload":{"message":"api_key_expired"}}\n'
    )
    note = drive(api, "pi-rpc", "builder", str(tmp_path), "Reply ok", expected="error")
    assert note["error_text"] == "api_key_expired"
    assert [step["step"] for step in note["steps"]] == [
        "launch",
        "stream_open",
        "error",
        "stop",
        "archive",
    ]


def test_driver_reads_reply_events_nested_in_watch_snapshot(tmp_path) -> None:
    api = FakeAPI()
    api.event_stream = BytesIO(
        b'data: {"type":"snapshot","events":['
        b'{"kind":"text","payload":{"text":"READY"}},'
        b'{"kind":"status","payload":{"status":"idle"}}]}\n'
    )
    note = drive(api, "pi-rpc", "builder", str(tmp_path), "Reply ok")
    assert "error" not in note
    assert [event["kind"] for event in note["events"]] == ["text", "status"]


def test_permission_request_is_recorded_and_never_approved(tmp_path) -> None:
    api = FakeAPI()
    api.event_stream = BytesIO(
        b'data: {"kind":"permission_requested","payload":'
        b'{"request_id":"p1","summary":"secret"}}\n'
    )
    note = drive(api, "claude-cli", "builder", str(tmp_path), "Reply ok")
    assert "permission_requested p1" in note["error"]
    assert note["events"] == [
        {"kind": "permission_requested", "payload_keys": ["request_id", "summary"]}
    ]
    assert api.calls == ["/api/agents"]


def test_launch_socket_timeout_returns_partial_note_with_stderr() -> None:
    class TimeoutAPI:
        stderr_tail = "runner diagnostic line"

        def request(self, path, payload=None):
            raise TimeoutError("read timed out")

    note = drive(TimeoutAPI(), "pi-rpc", "builder", "workspace", "Reply ok", model="m")
    assert note["harness"] == "pi-rpc"
    assert note["role"] == "builder"
    assert note["model"] == "m"
    assert "TimeoutError" in note["error"] or "timed out" in note["error"]
    assert note["steps"][0]["step"] == "launch"
    assert note["steps"][0]["status"] == "error"
    assert note["steps"][0]["elapsed_seconds"] >= 0
    assert "runner diagnostic line" in note["runner_stderr_tail"]


def test_wait_for_reply_times_out_when_stream_is_silent() -> None:
    reader, writer = socket.socketpair()
    stream = reader.makefile("rb")
    try:
        try:
            _MODULE.wait_for_reply(stream, 0.01)
        except TimeoutError as exc:
            assert "timed out" in str(exc)
        else:
            raise AssertionError("silent stream should time out")
    finally:
        stream.close()
        reader.close()
        writer.close()

from __future__ import annotations

from varde_runner.node_host.frames import Event
from varde_runner.plugins import SessionSpec
from varde_runner.plugins.claude_sdk.plugin import ClaudeSdkPlugin


def test_handle_event_persists_sdk_session_id(tmp_path) -> None:
    plugin = ClaudeSdkPlugin(state_dir=tmp_path)
    plugin._specs["00000000-0000-4000-8000-000000000001"] = SessionSpec(
        "claude-sdk", "sonnet", "workspace", "/workspace/project", "start"
    )
    sid = "00000000-0000-4000-8000-000000000001"
    plugin._handles[sid] = "sdk-session-id"
    plugin._save(sid)
    value = plugin._path(sid).read_text(encoding="utf-8")
    assert '"handle": "sdk-session-id"' in value


def test_event_shape_matches_node_host_frame() -> None:
    event = Event("text", "session-id", {"text": "hello"}, 1)
    assert event.event == "text"
    assert event.session == "session-id"
    assert event.data == {"text": "hello"}

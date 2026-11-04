import json
from pathlib import Path

import pytest
from varde_runner.plugins.claude_cli.wire import (
    build_command,
    encode_control_response,
    encode_interrupt,
    encode_user_message,
    parse_line,
)

FIXTURES = Path(__file__).parent / "fixtures" / "claude_cli"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("read-only", "plan"),
        ("workspace-write", "acceptEdits"),
        ("auto", "acceptEdits"),
        ("full-access", "bypassPermissions"),
        ("bot", "manual"),
    ],
)
def test_build_command_maps_modes(mode, expected):
    command = build_command("model-x", "high", mode, "session-1")
    assert command[:10] == [
        "claude",
        "--print",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--replay-user-messages",
        "--include-partial-messages",
        "--permission-prompts",
    ]
    assert command[10:12] == ["host", "--model"]
    assert command[command.index("--permission-mode") + 1] == expected
    assert "--include-partial-messages" in command
    assert command[-2:] == ["--session-id", "session-1"]


def test_unknown_mode_rejected():
    with pytest.raises(ValueError, match="unsupported runner mode"):
        build_command("model-x", None, "mystery", "s")


def test_resume_replaces_session_id():
    command = build_command("model-x", None, "auto", "s", resume_id="prior")
    assert command[-2:] == ["--resume", "prior"]


@pytest.mark.parametrize(
    ("model", "effort"),
    [("--inject", None), ("model-x", "--inject")],
)
def test_build_command_rejects_flag_injection(model, effort):
    with pytest.raises(ValueError, match="must not start"):
        build_command(model, effort, "auto", "s")


def test_encoders_emit_stream_json_frames():
    user = json.loads(encode_user_message("hello", "s"))
    assert user == {
        "type": "user",
        "message": {"role": "user", "content": "hello"},
        "parent_tool_use_id": None,
        "session_id": "s",
    }
    allow = json.loads(encode_control_response("r", "allow", {"command": "ls"}))
    assert allow["response"]["request_id"] == "r"
    assert allow["response"]["response"] == {
        "behavior": "allow",
        "updatedInput": {"command": "ls"},
    }
    deny = json.loads(encode_control_response("r", "deny", {}, "no"))
    assert deny["response"]["response"]["message"] == "no"
    default_deny = json.loads(encode_control_response("r", "deny", {}))
    assert default_deny["response"]["response"]["message"] == "Denied by Varde"
    interrupt = json.loads(encode_interrupt("interrupt-1"))
    assert interrupt["request_id"] == "interrupt-1"
    assert interrupt["request"]["subtype"] == "interrupt"


def test_replayed_user_message_with_string_content_is_ignored():
    event = parse_line(
        json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}}),
        "s",
    )
    assert event == []


def test_parse_assistant_and_tool_use_fixture():
    line = (FIXTURES / "assistant.jsonl").read_text()
    events = parse_line(line, "s")
    assert [(event.kind, event.payload.get("text")) for event in events] == [
        ("text", "Hello"),
        ("tool_intent", None),
    ]
    assert events[1].payload["call_id"] == "call-1"


def test_permission_summary_redacts_input():
    event = parse_line((FIXTURES / "permission.jsonl").read_text(), "s")[0]
    assert event.kind == "permission_requested"
    assert event.payload == {
        "request_id": "req-1",
        "tool_use_id": None,
        "kind": "tool",
        "tool": "Bash",
        "summary": "Permission requested for Bash",
        "input": {"command": "echo secret"},
    }
    assert event.payload["summary"] == "Permission requested for Bash"


def test_result_usage_and_idle_state_fixtures():
    events = parse_line((FIXTURES / "result.jsonl").read_text(), "s")
    assert [event.kind for event in events] == ["session_end", "status", "usage"]
    assert events[2].payload["usage"]["input_tokens"] == 12
    state = parse_line((FIXTURES / "session_state.jsonl").read_text(), "s")[0]
    assert state.kind == "status" and state.payload["status"] == "idle"


def test_stream_text_delta_and_context_tokens():
    delta = parse_line(
        json.dumps(
            {
                "type": "stream_event",
                "event": {
                    "type": "content_block_delta",
                    "delta": {"type": "text_delta", "text": "partial"},
                },
            }
        ),
        "s",
    )
    assert len(delta) == 1
    assert delta[0].kind == "text_delta"
    assert delta[0].payload == {"text": "partial"}

    events = parse_line(
        json.dumps(
            {
                "type": "result",
                "result": "final",
                "usage": {
                    "input_tokens": 17,
                    "output_tokens": 4,
                    "cache_read_input_tokens": 11,
                    "cache_creation_input_tokens": 9,
                },
            }
        ),
        "s",
    )
    usage = next(event for event in events if event.kind == "usage")
    assert usage.payload["context_tokens"] == 37
    assert usage.payload["usage"]["output_tokens"] == 4


@pytest.mark.parametrize(
    ("extra", "expected_status", "subtype"),
    [
        ({"is_error": True, "subtype": "success"}, "failed", "success"),
        ({"subtype": "error_max_turns"}, "failed", "error_max_turns"),
        ({"subtype": "success"}, "completed", "success"),
    ],
)
def test_result_status_reflects_failure(extra, expected_status, subtype):
    line = json.dumps({"type": "result", "result": "done", **extra})
    end = parse_line(line, "s")[0]
    assert end.payload == {
        "status": expected_status,
        "result": "done",
        "subtype": subtype,
    }


def test_tool_result_fixture():
    event = parse_line((FIXTURES / "tool_result.jsonl").read_text(), "s")[0]
    assert event.kind == "tool_result"
    assert event.payload["call_id"] == "call-1"


def test_malformed_line_becomes_error_event():
    events = parse_line("{not json", "s")
    assert len(events) == 1 and events[0].kind == "error"


@pytest.mark.parametrize(
    "line",
    [
        '{"type":"control_request","request":null}',
        '{"type":"assistant","message":"x"}',
        '{"type":"user","message":null}',
        '{"type":"control_request","request":{"subtype":"can_use_tool"}}',
        "[" + "{" * 1500 + "}" * 1500 + "]",
    ],
)
def test_malformed_shapes_never_raise(line):
    events = parse_line(line, "s")
    assert events
    assert all(event.kind == "error" for event in events)

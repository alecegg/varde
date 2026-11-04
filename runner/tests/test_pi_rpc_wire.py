from __future__ import annotations

import json

from varde_runner.plugins.pi_rpc import wire


def test_build_command_uses_verified_session_flags():
    assert wire.build_command("model", "abc") == [
        "pi",
        "--mode",
        "rpc",
        "--model",
        "model",
        "--tools",
        "read,grep,find,ls",
        "--exclude-tools",
        "mcp__*",
        "--session-id",
        "abc",
    ]
    assert wire.build_command("model", "abc", "session.jsonl")[-2:] == [
        "--session",
        "session.jsonl",
    ]


def test_command_ids_correlate_and_parse_errors_are_events():
    pending = {"r1": "prompt"}
    events, response = wire.parse_frame(
        b'{"type":"response","id":"r1","success":true}', "s", pending
    )
    assert events == []
    assert response == {
        "command": "prompt",
        "type": "response",
        "id": "r1",
        "success": True,
    }
    events, response = wire.parse_frame(b"not-json", "s")
    assert response is None
    assert events[0].kind == "error"


def test_dialogs_cancel_and_fire_and_forget_is_ignored():
    events, response = wire.parse_frame(
        b'{"type":"extension_ui_request","id":"d1","method":"confirm"}', "s"
    )
    assert events[0].kind == "error"
    assert response == {"extension_ui_cancel": "d1"}
    assert wire.parse_frame(
        b'{"type":"extension_ui_request","id":"n1","method":"notify"}', "s"
    ) == ([], None)


def test_lf_frame_keeps_unicode_line_separator_inside_json_string():
    events, _ = wire.parse_frame(
        json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "a\u2028b"}],
                },
            }
        ).encode(),
        "s",
    )
    assert events[0].payload["text"] == "a\u2028b"


def test_assistant_error_emits_bounded_error_and_preserves_text():
    detail = (
        '401: {"type":"authentication_error","code":"api_key_expired",'
        '"message":"This API key has expired. Create a new API key in OpenCode '
        "Console and replace it in your client or secret store. Signing in again "
        'will not renew this key."}'
    )
    events, _ = wire.parse_frame(
        json.dumps(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "visible text"}],
                    "stopReason": "error",
                    "errorMessage": detail,
                },
            }
        ).encode(),
        "s",
    )
    assert [
        (event.kind, event.payload.get("status"))
        for event in events
        if event.kind == "status"
    ] == [("status", "error")]
    error = next(event for event in events if event.kind == "error")
    assert error.payload["message"] == detail[:2048]
    assert any(
        event.kind == "text" and event.payload["text"] == "visible text"
        for event in events
    )


def test_agent_end_does_not_repeat_message_end_error():
    body = {
        "role": "assistant",
        "stopReason": "error",
        "errorMessage": "failure",
    }
    first, _ = wire.parse_frame(
        json.dumps({"type": "message_end", "message": body}).encode(), "s"
    )
    repeated, _ = wire.parse_frame(
        json.dumps(
            {
                "type": "agent_end",
                "messages": [body],
            }
        ).encode(),
        "s",
    )
    events = [*first, *repeated]
    assert [event.kind for event in events] == ["error", "status"]

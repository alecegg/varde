import json
from pathlib import Path

import pytest
from varde_runner.plugins.codex_app_server import wire


def unpack(value: str) -> dict:
    return json.loads(value)


@pytest.mark.parametrize(
    ("mode", "sandbox", "approval"),
    [
        ("read-only", "read-only", "never"),
        ("workspace-write", "workspace-write", "on-request"),
        ("auto", "workspace-write", "on-request"),
        ("full-access", "danger-full-access", "never"),
    ],
)
def test_mode_command(mode: str, sandbox: str, approval: str) -> None:
    command = wire.build_command(mode)
    assert command[:3] == ["codex", "app-server", "--stdio"]
    assert f'sandbox_mode="{sandbox}"' in command
    assert f'approval_policy="{approval}"' in command


def test_unknown_mode_rejected() -> None:
    with pytest.raises(ValueError):
        wire.build_command("mystery")


def test_protocol_encoders() -> None:
    assert unpack(wire.encode_initialize("1.2.3", 10))["method"] == "initialize"
    assert unpack(wire.encode_initialized())["method"] == "initialized"
    thread_start = unpack(wire.encode_thread_start("/workspace", "auto", None, 11))
    assert thread_start["method"] == "thread/start"
    assert thread_start["params"]["sandbox"] == "workspace-write"
    assert thread_start["params"]["approvalPolicy"] == "on-request"
    resume_params = unpack(
        wire.encode_thread_resume("t", "auto", "/workspace", None, 12)
    )["params"]
    assert resume_params == {
        "threadId": "t",
        "cwd": "/workspace",
        "sandbox": "workspace-write",
        "approvalPolicy": "on-request",
    }
    turn_start = unpack(wire.encode_turn_start("t", "go", 13, "low"))
    assert turn_start["method"] == "turn/start"
    assert turn_start["params"]["effort"] == "low"
    assert unpack(wire.encode_turn_start("t", "go", 13, " "))["params"] == {
        "threadId": "t",
        "input": [{"type": "text", "text": "go"}],
    }
    assert unpack(wire.encode_turn_steer("t", "u", "go", 14))["method"] == "turn/steer"
    assert (
        unpack(wire.encode_turn_interrupt("t", "u", 15))["method"] == "turn/interrupt"
    )
    assert (
        unpack(wire.encode_rate_limits_read(16))["method"] == "account/rateLimits/read"
    )


@pytest.mark.parametrize(
    "method",
    [
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
        "item/tool/requestUserInput",
    ],
)
def test_server_response(method: str) -> None:
    response = unpack(
        wire.encode_server_response(
            method, "x", "allow", permissions={"network": {"enabled": True}}
        )
    )
    assert response["id"] == "x" and "result" in response
    if method in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    }:
        assert response["result"] == {"decision": "accept"}
    elif method == "item/permissions/requestApproval":
        assert response["result"]["scope"] == "turn"
        assert response["result"]["permissions"] == {"network": {"enabled": True}}
    else:
        assert response["result"] == {"answers": {}}


def test_auth_refresh_is_refused() -> None:
    value = unpack(
        wire.encode_server_response("account/chatgptAuthTokens/refresh", "x", "allow")
    )
    assert value["error"]["code"] == -32601


def test_versions_and_missing_methods() -> None:
    assert wire.MINIMUM_VERSION == "0.162.1"
    assert wire.parse_version("codex-cli 0.162.1") == (0, 162, 1)
    assert wire.version_at_least("0.163.0", wire.MINIMUM_VERSION)
    assert not wire.version_at_least("0.162.0", wire.MINIMUM_VERSION)
    assert (
        wire.missing_methods(
            set(wire.REQUIRED_CLIENT_METHODS), set(wire.REQUIRED_SERVER_METHODS)
        )
        == ()
    )
    assert wire.missing_methods(set(), set()) == wire.REQUIRED_METHODS


def test_fixture_events_and_unknown_rate_limits() -> None:
    fixture = Path(__file__).parent / "fixtures/codex_app_server/events.jsonl"
    events = [
        event
        for line in fixture.read_text().splitlines()
        for event in wire.parse_line(line, "s")
    ]
    assert [event.kind for event in events] == [
        "status",
        "text",
        "tool_intent",
        "tool_result",
        "permission_requested",
        "permission_requested",
        "tool_result",
        "usage",
        "usage",
        "status",
        "session_end",
        "status",
        "permission_resolved",
    ]
    assert events[8].payload["limit"]["primary"]["used_percent"] == 24
    assert events[4].payload["rpc_id"] == 42
    assert events[10].payload["status"] == "failed"
    assert events[11].payload["status"] == "error"


def test_user_input_question_and_redaction() -> None:
    events = wire.parse_message(
        {
            "id": 3,
            "method": "item/tool/requestUserInput",
            "params": {"questions": [{"question": "Q", "access_token": "private"}]},
        },
        "s",
    )
    assert events[0].kind == "wait_created"
    expected = "[" + "redacted" + "]"
    assert events[0].payload["question"][0]["access_token"] == expected


def test_malformed_line() -> None:
    with pytest.raises(wire.WireError):
        wire.parse_line("not-json")


def test_integer_request_id_round_trip() -> None:
    request = {
        "id": 3,
        "method": "item/commandExecution/requestApproval",
        "params": {"command": "ls"},
    }
    event = wire.parse_message(request, "s")[0]
    assert event.payload["request_id"] == "3"
    assert event.payload["rpc_id"] == 3
    response = unpack(
        wire.encode_server_response(request["method"], event.payload["rpc_id"], "allow")
    )
    assert response["id"] == 3 and isinstance(response["id"], int)


def test_permissions_deny_and_allow_schema() -> None:
    denied = unpack(
        wire.encode_server_response("item/permissions/requestApproval", "1", "deny")
    )
    assert denied["result"] == {"permissions": {}}
    allowed = unpack(
        wire.encode_server_response(
            "item/permissions/requestApproval",
            2,
            "allow",
            permissions={"network": {"enabled": True}},
        )
    )
    assert allowed["result"] == {
        "permissions": {"network": {"enabled": True}},
        "scope": "turn",
    }
    with pytest.raises(ValueError):
        wire.encode_server_response("item/permissions/requestApproval", 2, "allow")


def test_request_ids_are_required_by_encoders() -> None:
    encoded = unpack(wire.encode_initialize("1.2.3", 24))
    assert encoded["id"] == 24
    assert encoded["params"]["clientInfo"]["version"] == "1.2.3"
    with pytest.raises(ValueError):
        wire.build_command("auto", 'x"\\ny')
    with pytest.raises(ValueError):
        wire.encode_thread_start("/workspace", "unsupported", None, 1)
    assert not issubclass(wire.WireError, ValueError)


def test_response_errors_and_rate_limit_response_are_normalized() -> None:
    rpc_error = wire.parse_message(
        {"id": 8, "error": {"code": -1, "message": "failed"}}, "s"
    )
    assert rpc_error[0].kind == "error"
    limits = wire.parse_message(
        {
            "method": "account/rateLimits/updated",
            "params": {
                "rateLimits": {
                    "limitId": "primary",
                    "primary": {
                        "usedPercent": 45,
                        "windowDurationMins": 300,
                        "resetsAt": 10,
                    },
                }
            },
        },
        "s",
    )[0]
    assert limits.payload["limit"]["primary"] == {
        "used_percent": 45,
        "window_minutes": 300,
        "resets_at": 10,
    }
    missing = wire.parse_message(
        {"method": "thread/tokenUsage/updated", "params": {"tokenUsage": None}}, "s"
    )[0]
    assert missing.payload["usage"] == "unknown"
    no_limits = wire.parse_message(
        {"method": "account/rateLimits/updated", "params": {"rateLimits": None}}, "s"
    )[0]
    assert no_limits.payload["limit"] == "unknown"
    response = wire.parse_message(
        {
            "id": 9,
            "result": {
                "rateLimits": {"limitId": "L"},
                "rateLimitsByLimitId": {
                    "L": {"limitId": "L", "primary": {"usedPercent": 9}}
                },
            },
        },
        "s",
        response_methods={9: "account/rateLimits/read"},
    )[0]
    assert response.kind == "usage" and response.payload["limit"]["limit_id"] == "L"
    assert response.payload["limit"]["by_limit_id"]["L"]["primary"]["used_percent"] == 9


def test_error_notification_retry_and_turn_status() -> None:
    retry = wire.parse_message(
        {
            "method": "error",
            "params": {
                "error": {"message": "retry"},
                "willRetry": True,
                "threadId": "thread-1",
                "turnId": "turn-1",
            },
        },
        "s",
    )[0]
    assert retry.kind == "status" and retry.payload == {
        "message": "retry",
        "will_retry": True,
        "thread_id": "thread-1",
        "turn_id": "turn-1",
    }
    terminal_error = wire.parse_message(
        {
            "method": "error",
            "params": {"error": {"message": "stop"}, "willRetry": False},
        },
        "s",
    )[0]
    assert (
        terminal_error.kind == "error" and terminal_error.payload["message"] == "stop"
    )
    failed = wire.parse_message(
        {
            "method": "turn/completed",
            "params": {"turn": {"status": "failed", "error": {"message": "x"}}},
        },
        "s",
    )[0]
    assert failed.payload["status"] == "failed"
    assert (
        wire.parse_message(
            {"method": "turn/completed", "params": {"turn": {"status": "interrupted"}}},
            "s",
        )[1].payload["status"]
        == "idle"
    )
    assert wire.parse_message({"method": "turn/started", "params": {}}, "s")[
        0
    ].payload == {"status": "running"}
    unknown = wire.parse_message(
        {"method": "turn/completed", "params": {"turn": {"items": []}}}, "s"
    )[0]
    assert unknown.payload["status"] == "unknown"


def test_unknown_notifications_are_ignored() -> None:
    assert wire.parse_message({"method": "future/notification", "params": {}}) == []


def test_missing_request_id_and_non_object_lines() -> None:
    with pytest.raises(wire.WireError):
        wire.parse_message({"method": "item/tool/requestUserInput", "params": {}})
    for line in ("[]", "1"):
        with pytest.raises(wire.WireError):
            wire.parse_line(line)


def test_resolved_question_uses_wait_event_when_caller_tracks_kind() -> None:
    event = wire.parse_message(
        {"method": "serverRequest/resolved", "params": {"requestId": 5}},
        request_kinds={5: "question"},
    )[0]
    assert event.kind == "wait_resolved"


def test_tool_question_answer_response_shape() -> None:
    answer = {"question_id": {"answers": ["yes"]}}
    response = unpack(
        wire.encode_server_response("item/tool/requestUserInput", 3, answer)
    )
    assert response["id"] == 3
    assert response["result"] == {"answers": answer}


def test_encoders_require_unique_request_ids() -> None:
    import inspect

    for encoder in (
        wire.encode_initialize,
        wire.encode_thread_start,
        wire.encode_thread_resume,
        wire.encode_turn_start,
        wire.encode_turn_steer,
        wire.encode_turn_interrupt,
        wire.encode_rate_limits_read,
    ):
        assert (
            inspect.signature(encoder).parameters["request_id"].default
            is inspect.Parameter.empty
        )


def test_permission_request_uses_decision_card_shape_and_redacts_summary() -> None:
    event = wire.parse_message(
        {
            "id": 7,
            "method": "item/commandExecution/requestApproval",
            "params": {
                "command": (
                    "curl --header 'Authorization: Bearer abc.def' api_key=secret"
                ),
                "itemId": "i1",
                "threadId": "th1",
                "turnId": "tu1",
            },
        },
        "s",
    )[0]
    assert event.payload == {
        "request_id": "7",
        "rpc_id": 7,
        "kind": "tool",
        "tool": "commandExecution",
        "item_id": "i1",
        "thread_id": "th1",
        "turn_id": "tu1",
        "summary": (
            "curl --header 'Authorization: Bearer [redacted]' api_key=[redacted]"
        ),
    }

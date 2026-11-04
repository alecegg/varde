import json
from pathlib import Path

from varde_runner.plugins import SessionSpec
from varde_runner.plugins.opencode_http.wire import (
    MODE_RULES,
    decode_sse,
    encode_session,
)

FIXTURE = Path(__file__).parent / "fixtures" / "opencode_2_0_18_subset.json"


def test_session_body_and_permissions_match_recorded_openapi():
    spec = json.loads(FIXTURE.read_text())
    body = encode_session(
        SessionSpec("openai", "model-id", "agent", "/workspace", mode_id="read-only"),
        "read-only",
    )
    model_schema = spec["schemas"]["Model.Ref"]
    assert set(body["model"]) == set(model_schema["required"])
    assert body["model"] == {"id": "model-id", "providerID": "openai"}
    assert all(
        set(rule) == set(spec["schemas"]["Permission.Rule"]["required"])
        for rule in body["permissions"]
    )
    assert MODE_RULES["read-only"] == [
        {"action": "*", "resource": "*", "effect": "deny"},
        {"action": "read", "resource": "*", "effect": "allow"},
    ]
    assert MODE_RULES["auto"] == MODE_RULES["workspace-write"]


def test_v2_event_samples_match_source_contract_fixture():
    fixture = json.loads(FIXTURE.read_text())
    for frame in fixture["event_source"]["frames"]:
        for event in decode_sse(json.dumps(frame), "runner-id", "ses_fixture"):
            assert event.session_id == "runner-id"
    decoded = [
        event
        for frame in fixture["event_source"]["frames"]
        for event in decode_sse(json.dumps(frame), "runner-id", "ses_fixture")
    ]
    assert [event.kind for event in decoded] == [
        "activity",
        "permission_requested",
        "question_requested",
        "question_requested",
        "usage",
        "status",
        "session_end",
    ]
    assert decoded[1].payload["request"]["resources"] == ["src/main.py"]
    assert decoded[2].payload["id"] == "frm_fixture"
    assert decoded[4].payload["tokens"]["input"] == 8


def test_unknown_permission_event_fails_closed_and_is_surfaced():
    event = decode_sse(
        '{"type":"permission.future_request","data":{"sessionID":"ses_fixture"}}',
        "runner-id",
        "ses_fixture",
    )[0]
    assert event.kind == "error"


def test_failed_execution_is_not_terminal():
    event = decode_sse(
        json.dumps(
            {
                "type": "session.execution.failed",
                "data": {"sessionID": "ses_fixture", "error": "process died"},
            }
        ),
        "runner-id",
        "ses_fixture",
    )[-1]
    assert event.kind == "session_end"
    assert event.payload == {"status": "failed"}

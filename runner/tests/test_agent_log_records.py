from varde_runner.agent_log import (
    tool_intent_payload,
    tool_result_payload,
)


def test_tool_payload_helpers_build_neutral_events():
    raw = {"provider": "shape"}
    assert tool_intent_payload("call-1", "shell", "running", raw) == {
        "call_id": "call-1",
        "tool": "shell",
        "phase": "running",
        "raw": raw,
    }
    assert tool_result_payload("call-1", "shell", "failed", raw) == {
        "call_id": "call-1",
        "tool": "shell",
        "phase": "failed",
        "raw": raw,
    }

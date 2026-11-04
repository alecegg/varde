"""Pure encoders and decoders for Claude Code's stream-json protocol."""

from __future__ import annotations

import json
from typing import Any

from varde_runner.agent_log import tool_intent_payload, tool_result_payload
from varde_runner.events import EventKind, RunnerEvent

MODE_MAP = {
    "read-only": "plan",
    "workspace-write": "acceptEdits",
    "auto": "acceptEdits",
    "full-access": "bypassPermissions",
    "bot": "manual",
}
TOOL_NAMES = {"read": "Read", "search": "Grep", "list": "Glob", "shell": "Bash"}
DENIED_TOOLS = ("WebFetch", "WebSearch")


def tool_names(kinds: tuple[str, ...]) -> list[str]:
    try:
        return [TOOL_NAMES[kind] for kind in kinds]
    except KeyError as exc:
        raise ValueError(f"unsupported tool kind: {exc.args[0]}") from exc


def restricted_settings() -> dict[str, Any]:
    """Generated settings for a restricted session: no allow rules, web tools denied."""
    return {"permissions": {"allow": [], "deny": list(DENIED_TOOLS)}}


def restricted_flags(settings_path: str, tools: list[str]) -> list[str]:
    """No user settings, MCP servers, customizations or extra directories."""
    return [
        "--restricted",
        "--tools",
        ",".join(tools),
        "--strict-mcp-config",
        "--safe-mode",
        "--settings",
        settings_path,
    ]


def build_command(
    model: str,
    effort: str | None,
    mode: str,
    session_id: str,
    resume_id: str | None = None,
) -> list[str]:
    if model.startswith("-") or (effort is not None and effort.startswith("-")):
        raise ValueError("model and effort must not start with '-'")
    try:
        permission_mode = MODE_MAP[mode]
    except KeyError as exc:
        raise ValueError(f"unsupported runner mode: {mode}") from exc
    command = [
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
        "host",
        "--model",
        model,
        "--permission-mode",
        permission_mode,
    ]
    if effort:
        command.extend(["--effort", effort])
    command.extend(
        ["--resume", resume_id] if resume_id else ["--session-id", session_id]
    )
    return command


def encode_user_message(text: str, session_id: str | None = None) -> str:
    return json.dumps(
        {
            "type": "user",
            "message": {"role": "user", "content": text},
            "parent_tool_use_id": None,
            "session_id": session_id,
        }
    )


def encode_control_response(
    request_id: str,
    decision: str | bool,
    original_input: dict[str, Any],
    message: str | None = None,
) -> str:
    allow = decision is True or decision == "allow"
    response: dict[str, Any] = {"behavior": "allow" if allow else "deny"}
    if allow:
        response["updatedInput"] = original_input
    else:
        response["message"] = message or "Denied by Varde"
    return json.dumps(
        {
            "type": "control_response",
            "response": {
                "subtype": "success",
                "request_id": request_id,
                "response": response,
            },
        }
    )


def encode_interrupt(request_id: str) -> str:
    return json.dumps(
        {
            "type": "control_request",
            "request_id": request_id,
            "request": {"subtype": "interrupt"},
        }
    )


def parse_line(line: str, session_id: str) -> list[RunnerEvent]:
    try:
        message = json.loads(line)
        if not isinstance(message, dict):
            return [
                _event(
                    "error", session_id, {"message": "stream frame must be an object"}
                )
            ]
        return _parse_message(message, session_id)
    except (ValueError, TypeError, RecursionError, AttributeError) as exc:
        return [
            _event(
                "error", session_id, {"message": f"malformed Claude stream line: {exc}"}
            )
        ]


def _parse_message(message: dict[str, Any], session_id: str) -> list[RunnerEvent]:
    kind = message.get("type")
    if kind == "stream_event":
        return _stream_events(message, session_id)
    handlers = {
        "assistant": _assistant_events,
        "user": _tool_results,
        "control_request": _control_request_event,
        "result": _result_events,
    }
    handler = handlers.get(kind) if isinstance(kind, str) else None
    if handler is not None:
        return handler(message, session_id)
    if kind == "system" and message.get("subtype") == "session_state_changed":
        return _session_state_event(message, session_id)
    if kind == "rate_limit_event":
        return [
            _event(
                "usage",
                session_id,
                {"limit": message.get("rate_limit_info", message), "source": "claude"},
            )
        ]
    if kind == "error":
        return [_event("error", session_id, {"message": message.get("error", message)})]
    return []


def _assistant_events(message: dict[str, Any], session_id: str) -> list[RunnerEvent]:
    body = message.get("message")
    if not isinstance(body, dict):
        return [
            _event(
                "error",
                session_id,
                {"message": "assistant frame message must be an object"},
            )
        ]
    content = body.get("content", [])
    if not isinstance(content, list):
        return [
            _event("error", session_id, {"message": "assistant content must be a list"})
        ]
    events = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            events.append(_event("text", session_id, {"text": block.get("text", "")}))
        elif block.get("type") == "tool_use":
            call_id = block.get("id", "")
            events.append(
                _event(
                    "tool_intent",
                    session_id,
                    tool_intent_payload(
                        call_id,
                        block.get("name"),
                        "running",
                        {"input": block.get("input")},
                    ),
                )
            )
    return events


def _stream_events(message: dict[str, Any], session_id: str) -> list[RunnerEvent]:
    event = message.get("event")
    if not isinstance(event, dict) or event.get("type") != "content_block_delta":
        return []
    delta = event.get("delta")
    if not isinstance(delta, dict) or delta.get("type") != "text_delta":
        return []
    text = delta.get("text")
    if not isinstance(text, str):
        return []
    return [_event("text_delta", session_id, {"text": text})]


def _tool_results(message: dict[str, Any], session_id: str) -> list[RunnerEvent]:
    body = message.get("message")
    if not isinstance(body, dict):
        return [
            _event(
                "error", session_id, {"message": "user frame message must be an object"}
            )
        ]
    content = body.get("content", [])
    if isinstance(content, str):
        return []
    if not isinstance(content, list):
        return [_event("error", session_id, {"message": "user content must be a list"})]
    events = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            call_id = block.get("tool_use_id", "")
            events.append(
                _event(
                    "tool_result",
                    session_id,
                    tool_result_payload(
                        call_id,
                        None,
                        "failed" if block.get("is_error") else "completed",
                        {"content": block.get("content")},
                    ),
                )
            )
    return events


def _control_request_event(
    message: dict[str, Any], session_id: str
) -> list[RunnerEvent]:
    request = message.get("request")
    if not isinstance(request, dict):
        return [
            _event(
                "error", session_id, {"message": "control request must be an object"}
            )
        ]
    if request.get("subtype") != "can_use_tool":
        return []
    request_id = message.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        return [
            _event(
                "error", session_id, {"message": "permission request has no request_id"}
            )
        ]
    return [_permission_event(request_id, request, session_id)]


def _permission_event(
    request_id: str, request: dict[str, Any], session_id: str
) -> RunnerEvent:
    tool_name = request.get("tool_name", "unknown")
    original_input = request.get("input")
    if not isinstance(original_input, dict):
        original_input = {}
    summary = f"Permission requested for {tool_name}"
    return _event(
        "permission_requested",
        session_id,
        {
            "request_id": request_id,
            "tool_use_id": request.get("tool_use_id"),
            "kind": "tool",
            "tool": tool_name,
            "summary": summary,
            "input": original_input,
        },
    )


def _usage_event(message: dict[str, Any], session_id: str) -> RunnerEvent:
    result = message.get("result")
    usage = message.get("usage")
    usage_data = usage if isinstance(usage, dict) else {}
    context_tokens = sum(
        value
        for value in (
            usage_data.get("input_tokens"),
            usage_data.get("cache_read_input_tokens"),
            usage_data.get("cache_creation_input_tokens"),
        )
        if isinstance(value, int) and not isinstance(value, bool)
    )
    return _event(
        "usage",
        session_id,
        {
            "usage": usage if isinstance(usage, dict) else "unknown",
            "context_tokens": context_tokens,
            "source": "claude",
            "result": result,
        },
    )


def _result_events(message: dict[str, Any], session_id: str) -> list[RunnerEvent]:
    subtype = message.get("subtype")
    failed = message.get("is_error") is True or (
        isinstance(subtype, str) and subtype.startswith("error_")
    )
    payload: dict[str, Any] = {
        "status": "failed" if failed else "completed",
        "result": message.get("result"),
    }
    if subtype is not None:
        payload["subtype"] = subtype
    return [
        _event("session_end", session_id, payload),
        _event("status", session_id, {"status": "idle"}),
        _usage_event(message, session_id),
    ]


def _session_state_event(message: dict[str, Any], session_id: str) -> list[RunnerEvent]:
    state_value = message.get("state")
    state = state_value.get("name") if isinstance(state_value, dict) else state_value
    return [
        _event(
            "status",
            session_id,
            {
                "status": "idle" if state == "idle" else "running",
                "session_state": state,
            },
        )
    ]


def _event(kind: EventKind, session_id: str, payload: dict[str, Any]) -> RunnerEvent:
    return RunnerEvent(
        kind=kind, session_id=session_id, payload=payload, provider_id="claude-cli"
    )

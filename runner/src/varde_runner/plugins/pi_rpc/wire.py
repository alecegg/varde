"""JSONL helpers for Pi RPC mode."""

from __future__ import annotations

import json
from typing import Any

from varde_runner.events import EventKind, RunnerEvent


def build_command(
    model: str,
    session_id: str,
    session_file: str | None = None,
    reasoning_effort: str | None = None,
    mode: str = "read-only",
) -> list[str]:
    command = ["pi", "--mode", "rpc", "--model", model]
    if reasoning_effort:
        command.extend(["--thinking", reasoning_effort])
    if mode != "read-only":
        raise ValueError(f"unsupported runner mode: {mode}")
    command.extend(["--tools", "read,grep,find,ls", "--exclude-tools", "mcp__*"])
    if session_file:
        command.extend(["--session", session_file])
    else:
        command.extend(["--session-id", session_id])
    return command


def encode_command(command: str, request_id: str, **fields: Any) -> str:
    return json.dumps({"type": command, "id": request_id, **fields}, ensure_ascii=False)


def encode_extension_ui_cancel(request_id: str) -> str:
    return json.dumps(
        {"type": "extension_ui_response", "id": request_id, "cancelled": True}
    )


def parse_frame(  # noqa: PLR0911 - protocol frame kinds have distinct results.
    frame: bytes, session_id: str, pending: dict[str, str] | None = None
) -> tuple[list[RunnerEvent], dict[str, Any] | None]:
    try:
        message = json.loads(frame.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        return [
            _event(session_id, "error", {"message": f"malformed Pi RPC frame: {exc}"})
        ], None
    if not isinstance(message, dict):
        return [
            _event(session_id, "error", {"message": "Pi RPC frame must be an object"})
        ], None
    if message.get("type") == "response":
        command_id = message.get("id")
        command = (
            pending.pop(command_id, None)
            if isinstance(command_id, str) and pending is not None
            else None
        )
        return [], {"command": command, **message}
    if message.get("type") == "extension_ui_request":
        request_id, method = message.get("id"), message.get("method")
        if method in {"select", "confirm", "input", "editor"} and isinstance(
            request_id, str
        ):
            return [
                _event(
                    session_id,
                    "error",
                    {
                        "message": "Pi extension dialog cancelled: no approval UI "
                        "is available",
                        "request_id": request_id,
                    },
                )
            ], {"extension_ui_cancel": request_id}
        return [], None
    kind = message.get("type")
    if kind == "message_end":
        body = message.get("message")
        if isinstance(body, dict) and body.get("role") == "assistant":
            events: list[RunnerEvent] = []
            error_message = body.get("errorMessage")
            stop_reason = body.get("stopReason")
            if stop_reason == "error" or (
                isinstance(error_message, str) and error_message.strip()
            ):
                detail = error_message.strip() if isinstance(error_message, str) else ""
                message_text = detail or "Pi assistant message failed"
                events.extend(
                    [
                        _event(session_id, "error", {"message": message_text[:2048]}),
                        _event(session_id, "status", {"status": "error"}),
                    ]
                )
            content = body.get("content", [])
            texts = (
                [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                ]
                if isinstance(content, list)
                else []
            )
            text = "".join(item for item in texts if isinstance(item, str))
            if text:
                events.append(_event(session_id, "text", {"text": text}))
            return events, None
    if kind == "agent_end":
        # Assistant message failures are emitted by message_end. Pi repeats
        # those messages here, so reporting errors again would duplicate events.
        return [], None
    if kind == "agent_start":
        return [_event(session_id, "status", {"status": "running"})], None
    if kind == "agent_settled":
        return [
            _event(
                session_id,
                "status",
                {"status": "idle", "aborted": bool(message.get("aborted"))},
            )
        ], None
    if kind == "extension_error":
        return [
            _event(
                session_id,
                "error",
                {"message": message.get("error", "Pi extension error")},
            )
        ], None
    return [], None


def _event(session_id: str, kind: EventKind, payload: dict[str, Any]) -> RunnerEvent:
    return RunnerEvent(
        kind=kind, session_id=session_id, payload=payload, provider_id="pi-rpc"
    )

"""OpenCode V2 event and request helpers, checked against its current schemas."""

from __future__ import annotations

import json
from typing import Any

from varde_runner.events import RunnerEvent

MODE_RULES = {
    "read-only": [
        {"action": "*", "resource": "*", "effect": "deny"},
        {"action": "read", "resource": "*", "effect": "allow"},
    ],
    "workspace-write": [
        {"action": "*", "resource": "*", "effect": "ask"},
        {"action": "read", "resource": "*", "effect": "allow"},
        {"action": "edit", "resource": "*", "effect": "allow"},
    ],
    "auto": [
        {"action": "*", "resource": "*", "effect": "ask"},
        {"action": "read", "resource": "*", "effect": "allow"},
        {"action": "edit", "resource": "*", "effect": "allow"},
    ],
    "full-access": [{"action": "*", "resource": "*", "effect": "allow"}],
}

SESSION_EVENTS = {
    "permission.asked",
    "permission.replied",
    "form.created",
    "form.replied",
    "form.cancelled",
    "session.idle",
    "session.status",
    "session.usage.updated",
    "session.execution.started",
    "session.execution.succeeded",
    "session.execution.failed",
    "session.execution.interrupted",
    "session.step.started",
    "session.text.delta",
    "session.text.ended",
    "session.tool.called",
    "session.tool.progress",
    "session.tool.success",
    "session.tool.failed",
}


def decode_sse(  # noqa: C901, PLR0911, PLR0912 - maps distinct source event types.
    data: str, runner_session_id: str, opencode_session_id: str
) -> list[RunnerEvent]:
    try:
        event = json.loads(data)
    except ValueError, RecursionError:
        return [
            _event(runner_session_id, "error", {"message": "malformed OpenCode event"})
        ]
    if not isinstance(event, dict):
        return [
            _event(
                runner_session_id,
                "error",
                {"message": "OpenCode event must be an object"},
            )
        ]
    kind = event.get("type")
    payload = event.get("data")
    if not isinstance(payload, dict):
        payload = {}
    if kind == "server.connected":
        return []
    event_session_id = payload.get("sessionID")
    if kind in SESSION_EVENTS:
        missing_id = kind == "permission.asked" and not isinstance(
            payload.get("id"), str
        )
        if not isinstance(event_session_id, str) or missing_id:
            return [
                _event(
                    runner_session_id, "error", {"message": f"unparseable {kind} event"}
                )
            ]
        if event_session_id != opencode_session_id:
            return []
    if isinstance(event_session_id, str) and event_session_id != opencode_session_id:
        return []
    if kind == "permission.asked":
        return [
            _event(
                runner_session_id,
                "permission_requested",
                {"request_id": payload["id"], "request": payload},
            )
        ]
    if kind == "permission.replied":
        return [_event(runner_session_id, "permission_resolved", payload)]
    if kind == "form.created":
        form = payload.get("form")
        if not isinstance(form, dict) or not isinstance(form.get("id"), str):
            return [
                _event(
                    runner_session_id,
                    "error",
                    {"message": "unparseable form.created event"},
                )
            ]
        return [
            _event(
                runner_session_id, "question_requested", {"kind": "question", **form}
            )
        ]
    if kind in {"form.replied", "form.cancelled"}:
        return [_event(runner_session_id, "wait_resolved", payload)]
    if kind == "session.status":
        status = payload.get("status")
        status_type = status.get("type") if isinstance(status, dict) else None
        return [
            _event(
                runner_session_id,
                "status",
                {
                    "status": "running" if status_type == "busy" else "idle",
                    "detail": status,
                },
            )
        ]
    if kind == "session.idle":
        return [_event(runner_session_id, "status", {"status": "idle"})]
    if kind == "session.usage.updated":
        return [
            _event(
                runner_session_id,
                "usage",
                {"tokens": payload.get("tokens"), "cost": payload.get("cost")},
            )
        ]
    if kind == "session.execution.started":
        return [_event(runner_session_id, "status", {"status": "running"})]
    if kind in {"session.execution.succeeded", "session.execution.interrupted"}:
        status = "completed" if kind.endswith("succeeded") else "interrupted"
        return [_event(runner_session_id, "session_end", {"status": status})]
    if kind == "session.execution.failed":
        return [
            _event(runner_session_id, "error", {"error": payload.get("error")}),
            _event(
                runner_session_id,
                "session_end",
                {"status": "failed"},
            ),
        ]
    if kind == "session.text.delta":
        return [_event(runner_session_id, "text", {"text": payload.get("delta", "")})]
    if kind in {
        "session.tool.called",
        "session.tool.progress",
        "session.tool.success",
        "session.tool.failed",
    }:
        return [_event(runner_session_id, "tool", {"event": kind, **payload})]
    if kind in SESSION_EVENTS:
        return [_event(runner_session_id, "activity", {"event": kind, **payload})]
    if isinstance(kind, str) and kind.startswith(("permission.", "form.")):
        return [
            _event(
                runner_session_id,
                "error",
                {"message": f"unsupported request event {kind}"},
            )
        ]
    return [_event(runner_session_id, "activity", {"event": kind, "data": payload})]


def encode_session(spec: Any, mode: str) -> dict[str, Any]:
    if mode not in MODE_RULES:
        raise ValueError(f"unsupported OpenCode mode: {mode}")
    model = {"id": spec.model, "providerID": spec.provider}
    if spec.reasoning_effort:
        model["variant"] = spec.reasoning_effort
    return {
        "model": model,
        "location": {"directory": spec.cwd},
        "permissions": MODE_RULES[mode],
    }


def _event(session_id: str, kind: str, payload: dict[str, Any]) -> RunnerEvent:
    return RunnerEvent(kind, session_id, payload, "opencode-http")  # type: ignore[arg-type]

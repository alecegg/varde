"""Pure JSON-RPC wire helpers for Codex app-server over stdio."""

from __future__ import annotations

import json
import re
from typing import Any

from varde_runner.agent_log import tool_intent_payload, tool_result_payload
from varde_runner.events import EventKind, RunnerEvent

MINIMUM_VERSION = "0.162.1"
REQUIRED_CLIENT_METHODS = (
    "initialize",
    "initialized",
    "thread/start",
    "thread/resume",
    "turn/start",
    "turn/steer",
    "turn/interrupt",
    "account/rateLimits/read",
)
REQUIRED_SERVER_METHODS = (
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
    "item/tool/requestUserInput",
    "serverRequest/resolved",
)
# Client methods include the `initialized` notification; server methods include
# both request and notification names required by the adapter startup probe.
REQUIRED_METHODS = REQUIRED_CLIENT_METHODS + REQUIRED_SERVER_METHODS
MODE_MAP = {
    "read-only": {"sandbox": "read-only", "approvalPolicy": "never"},
    "workspace-write": {"sandbox": "workspace-write", "approvalPolicy": "on-request"},
    "auto": {"sandbox": "workspace-write", "approvalPolicy": "on-request"},
    "full-access": {"sandbox": "danger-full-access", "approvalPolicy": "never"},
}


class WireError(Exception):
    """Invalid JSON-line or unsupported protocol value."""


def build_command(mode: str, model: str | None = None) -> list[str]:
    try:
        policy = MODE_MAP[mode]
    except KeyError as exc:
        raise ValueError(f"unsupported runner mode: {mode}") from exc
    command = [
        "codex",
        "app-server",
        "--stdio",
        "-c",
        f'sandbox_mode="{policy["sandbox"]}"',
        "-c",
        f'approval_policy="{policy["approvalPolicy"]}"',
    ]
    if model:
        if model.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._:/-]+", model):
            raise ValueError("model contains unsupported characters")
        command.extend(["-c", f'model="{model}"'])
    return command


def encode_request(method: str, params: dict[str, Any], request_id: str | int) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    )


def encode_initialize(client_version: str, request_id: str | int) -> str:
    return encode_request(
        "initialize",
        {"clientInfo": {"name": "varde", "title": "Varde", "version": client_version}},
        request_id,
    )


def encode_initialized() -> str:
    return json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}})


def encode_thread_start(
    cwd: str, mode: str, model: str | None, request_id: str | int
) -> str:
    if mode not in MODE_MAP:
        raise ValueError(f"unsupported runner mode: {mode}")
    params: dict[str, Any] = {"cwd": cwd, **MODE_MAP[mode]}
    if model:
        params["model"] = model
    return encode_request("thread/start", params, request_id)


def encode_thread_resume(
    thread_id: str, mode: str, cwd: str, model: str | None, request_id: str | int
) -> str:
    if mode not in MODE_MAP:
        raise ValueError(f"unsupported runner mode: {mode}")
    params: dict[str, Any] = {"threadId": thread_id, "cwd": cwd, **MODE_MAP[mode]}
    if model:
        params["model"] = model
    return encode_request("thread/resume", params, request_id)


def encode_turn_start(
    thread_id: str, text: str, request_id: str | int, effort: str | None = None
) -> str:
    params: dict[str, Any] = {
        "threadId": thread_id,
        "input": [{"type": "text", "text": text}],
    }
    if isinstance(effort, str) and effort.strip():
        params["effort"] = effort.strip()
    return encode_request(
        "turn/start",
        params,
        request_id,
    )


def encode_turn_steer(
    thread_id: str, turn_id: str, text: str, request_id: str | int
) -> str:
    return encode_request(
        "turn/steer",
        {
            "threadId": thread_id,
            "expectedTurnId": turn_id,
            "input": [{"type": "text", "text": text}],
        },
        request_id,
    )


def encode_turn_interrupt(thread_id: str, turn_id: str, request_id: str | int) -> str:
    return encode_request(
        "turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, request_id
    )


def encode_rate_limits_read(request_id: str | int) -> str:
    return encode_request("account/rateLimits/read", {}, request_id)


def encode_server_response(
    method: str,
    request_id: str | int,
    decision: str | bool | dict[str, Any],
    permissions: dict[str, Any] | None = None,
    scope: str = "turn",
) -> str:
    approved = decision is True or decision == "allow"
    if method in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
    }:
        result = {"decision": "accept" if approved else "decline"}
    elif method == "item/permissions/requestApproval":
        if approved:
            grant = (
                permissions
                if permissions is not None
                else (decision if isinstance(decision, dict) else None)
            )
            if grant is None:
                raise ValueError(
                    "approved permission response requires a grant profile"
                )
            if scope not in {"turn", "session"}:
                raise ValueError(f"unsupported permission grant scope: {scope}")
            result = {"permissions": grant, "scope": scope}
        else:
            result = {"permissions": {}}
    elif method == "item/tool/requestUserInput":
        result = {"answers": decision if isinstance(decision, dict) else {}}
    else:
        return encode_error_response(request_id, -32601, "Unsupported server request")
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result})


def encode_error_response(
    request_id: str | int,
    code: int = -32601,
    message: str = "Unsupported server request",
) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
    )


def parse_message(  # noqa: C901, PLR0911, PLR0912
    obj: dict[str, Any],
    session_id: str = "",
    request_kinds: dict[str | int, str] | None = None,
    response_methods: dict[str | int, str] | None = None,
) -> list[RunnerEvent]:
    if not isinstance(obj, dict):
        raise WireError("JSON-RPC frame must be an object")
    method = obj.get("method")
    raw_params = obj.get("params")
    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
    if not isinstance(method, str):
        if "error" in obj:
            rpc_error = obj.get("error")
            return [_event("error", session_id, {"message": rpc_error})]
        if "result" in obj:
            request_id = obj.get("id")
            response_method = (
                (response_methods or {}).get(request_id)
                if isinstance(request_id, (str, int))
                and not isinstance(request_id, bool)
                else None
            )
            result = obj["result"]
            if response_method == "account/rateLimits/read" and isinstance(
                result, dict
            ):
                limit = _normalize_rate_limits(result.get("rateLimits"))
                buckets = result.get("rateLimitsByLimitId")
                if isinstance(limit, dict) and isinstance(buckets, dict):
                    limit["by_limit_id"] = {
                        key: _normalize_rate_limits(value)
                        for key, value in buckets.items()
                    }
                return [
                    _event("usage", session_id, {"limit": limit, "source": "codex"})
                ]
            return [
                _event(
                    "status", session_id, {"response_id": request_id, "result": result}
                )
            ]
        return []
    if method in {
        "item/tool/requestUserInput",
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
    } and (
        "id" not in obj
        or not isinstance(obj["id"], (str, int))
        or isinstance(obj["id"], bool)
    ):
        raise WireError("server request has no valid request id")
    if method == "item/tool/requestUserInput":
        return [
            _event(
                "wait_created",
                session_id,
                {
                    "request_id": str(obj["id"]),
                    "rpc_id": obj["id"],
                    "question": _redact(params.get("questions", [])),
                },
            )
        ]
    if method in {
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
    }:
        tool = {
            "item/commandExecution/requestApproval": "commandExecution",
            "item/fileChange/requestApproval": "fileChange",
            "item/permissions/requestApproval": "permissions",
        }[method]
        summary = (
            params.get("command") or params.get("reason") or params.get("grantRoot")
        )
        if summary is None:
            summary = params.get("permissions") or method
        summary = _redact_summary(str(summary))
        return [
            _event(
                "permission_requested",
                session_id,
                {
                    "request_id": str(obj["id"]),
                    "rpc_id": obj["id"],
                    "kind": "tool",
                    "tool": tool,
                    "item_id": params.get("itemId"),
                    "thread_id": params.get("threadId"),
                    "turn_id": params.get("turnId"),
                    "summary": summary,
                },
            )
        ]
    if method == "serverRequest/resolved":
        request_id = params.get("requestId", "")
        resolved_kind = (request_kinds or {}).get(request_id, "permission")
        event_kind = (
            "wait_resolved" if resolved_kind == "question" else "permission_resolved"
        )
        return [_event(event_kind, session_id, {"request_id": str(request_id)})]
    if method == "thread/tokenUsage/updated":
        return [
            _event(
                "usage",
                session_id,
                {
                    "usage": _normalize_token_usage(params.get("tokenUsage")),
                    "source": "codex",
                },
            )
        ]
    if method == "account/rateLimits/updated":
        return [
            _event(
                "usage",
                session_id,
                {
                    "limit": _normalize_rate_limits(params.get("rateLimits")),
                    "source": "codex",
                },
            )
        ]
    if method == "item/agentMessage/delta":
        return [_event("text", session_id, {"text": params.get("delta", "")})]
    if method == "item/started":
        item = params.get("item")
        if isinstance(item, dict) and item.get("type") in {
            "commandExecution",
            "fileChange",
        }:
            return [
                _event(
                    "tool_intent",
                    session_id,
                    tool_intent_payload(
                        str(item.get("id", "")),
                        item.get("type"),
                        "running",
                        _redact(item),
                    ),
                )
            ]
    if method == "item/completed":
        item = params.get("item")
        if isinstance(item, dict) and item.get("type") in {
            "commandExecution",
            "fileChange",
        }:
            return [
                _event(
                    "tool_result",
                    session_id,
                    tool_result_payload(
                        str(item.get("id", "")),
                        item.get("type"),
                        "completed" if item.get("status") == "completed" else "failed",
                        _redact(item),
                    ),
                )
            ]
    if method == "turn/completed":
        raw_turn = params.get("turn")
        turn: dict[str, Any] = raw_turn if isinstance(raw_turn, dict) else params
        status = turn.get("status")
        if status == "inProgress":
            return [_event("status", session_id, {"status": "running"})]
        outcome = (
            status if status in {"completed", "interrupted", "failed"} else "unknown"
        )
        session_status = "idle" if outcome in {"completed", "interrupted"} else "error"
        return [
            _event(
                "session_end",
                session_id,
                {"status": outcome, "error": turn.get("error")},
            ),
            _event("status", session_id, {"status": session_status}),
        ]
    if method == "turn/started":
        return [_event("status", session_id, {"status": "running"})]
    if method == "error":
        error = params.get("error")
        error = error if isinstance(error, dict) else {}
        payload = {
            "message": error.get("message", "unknown Codex error"),
            "will_retry": params.get("willRetry", False),
            "thread_id": params.get("threadId"),
            "turn_id": params.get("turnId"),
        }
        return (
            [_event("status", session_id, payload)]
            if payload["will_retry"]
            else [_event("error", session_id, payload)]
        )
    return []


def parse_line(
    line: str,
    session_id: str = "",
    request_kinds: dict[str | int, str] | None = None,
    response_methods: dict[str | int, str] | None = None,
) -> list[RunnerEvent]:
    try:
        value = json.loads(line)
        if not isinstance(value, dict):
            raise WireError("JSON-RPC frame must be an object")
        return parse_message(value, session_id, request_kinds, response_methods)
    except (json.JSONDecodeError, TypeError, RecursionError) as exc:
        raise WireError(f"malformed Codex app-server line: {exc}") from exc


def parse_version(text: str) -> tuple[int, ...]:
    match = re.search(r"(?<!\d)(\d+(?:\.\d+){1,3})", text)
    if match is None:
        raise ValueError(f"no version found in: {text!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def version_at_least(version: str, minimum: str) -> bool:
    left, right = parse_version(version), parse_version(minimum)
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) >= right + (0,) * (width - len(right))


def missing_methods(
    schema_client_methods: set[str], schema_server_methods: set[str]
) -> tuple[str, ...]:
    """Compare client-side and server-side schema method inventories."""
    missing = [
        method
        for method in REQUIRED_CLIENT_METHODS
        if method not in schema_client_methods
    ]
    missing.extend(
        method
        for method in REQUIRED_SERVER_METHODS
        if method not in schema_server_methods
    )
    return tuple(missing)


def _normalize_token_usage(value: Any) -> dict[str, Any] | str:
    if not isinstance(value, dict):
        return "unknown"
    last = value.get("last")
    total = value.get("total")
    return {
        "last": _token_counts(last),
        "total": _token_counts(total),
        "context_window": value.get("modelContextWindow", "unknown"),
    }


def _token_counts(value: Any) -> dict[str, Any] | str:
    if not isinstance(value, dict):
        return "unknown"
    return {
        "input_tokens": value.get("inputTokens", "unknown"),
        "cached_input_tokens": value.get("cachedInputTokens", "unknown"),
        "output_tokens": value.get("outputTokens", "unknown"),
        "reasoning_output_tokens": value.get("reasoningOutputTokens", "unknown"),
        "total_tokens": value.get("totalTokens", "unknown"),
    }


def _normalize_rate_limits(value: Any) -> dict[str, Any] | str:
    if not isinstance(value, dict):
        return "unknown"
    return {
        "limit_id": value.get("limitId", "unknown"),
        "plan_type": value.get("planType", "unknown"),
        "reached_type": value.get("rateLimitReachedType", "unknown"),
        "primary": _normalize_window(value.get("primary")),
        "secondary": _normalize_window(value.get("secondary")),
        "credits": value.get("credits", "unknown"),
    }


def _normalize_window(value: Any) -> dict[str, Any] | str:
    if not isinstance(value, dict):
        return "unknown"
    return {
        "used_percent": value.get("usedPercent", "unknown"),
        "window_minutes": value.get("windowDurationMins", "unknown"),
        "resets_at": value.get("resetsAt", "unknown"),
    }


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[redacted]"
                if any(
                    word in key.casefold() for word in ("secret", "token", "password")
                )
                else _redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _redact_summary(value: str) -> str:
    """Redact likely inline credentials before exposing a decision summary."""
    value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[redacted]", value)
    return re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)(\s*[:=]\s*)[^\s,;]+",
        r"\1\2[redacted]",
        value,
    )


def _event(kind: EventKind, session_id: str, payload: dict[str, Any]) -> RunnerEvent:
    return RunnerEvent(
        kind=kind, session_id=session_id, payload=payload, provider_id="codex"
    )

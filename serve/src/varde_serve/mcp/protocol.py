"""JSON-RPC 2.0 handling for the MCP subset a stdio server needs. Pure."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from varde_serve.mcp.tools import TOOLS, BadArguments

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_VERSIONS = (PROTOCOL_VERSION, "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "varde-serve", "version": "1"}
Call = Callable[[str, dict[str, Any]], tuple[bool, Any]]  # -> (is_error, payload)


def _reply(message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: Any, code: int, text: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": text},
    }


def _tool_result(is_error: bool, payload: Any) -> dict[str, Any]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def handle(message: Any, call: Call) -> dict[str, Any] | None:
    """Answer one decoded message; None for notifications."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "invalid request")
    method, message_id = message.get("method"), message.get("id")
    if message_id is None:
        return None  # notification: initialized, cancelled, ...
    raw_params = message.get("params")
    params: dict[str, Any] = raw_params if isinstance(raw_params, dict) else {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in SUPPORTED_VERSIONS else PROTOCOL_VERSION
        return _reply(
            message_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "ping":
        return _reply(message_id, {})
    if method == "tools/list":
        return _reply(message_id, {"tools": TOOLS})
    if method == "tools/call":
        return _call_tool(message_id, params, call)
    return _error(message_id, -32601, f"method not found: {method}")


def _call_tool(message_id: Any, params: dict[str, Any], call: Call) -> dict[str, Any]:
    arguments = params.get("arguments")
    arguments = arguments if isinstance(arguments, dict) else {}
    try:
        is_error, payload = call(str(params.get("name")), arguments)
    except BadArguments as error:
        return _error(message_id, -32602, str(error))
    return _reply(message_id, _tool_result(is_error, payload))

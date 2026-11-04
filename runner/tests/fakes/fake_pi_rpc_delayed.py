#!/usr/bin/env python3
"""Replay a delayed, batched Pi RPC turn with large protocol frames."""

from __future__ import annotations

import json
import sys
import time


def emit(record: dict) -> None:
    sys.stdout.write(json.dumps(record, ensure_ascii=False) + "\n")
    sys.stdout.flush()


# Pi may take time to initialize extensions before it starts consuming stdin.
time.sleep(1)
for line in sys.stdin:
    command = json.loads(line)
    if command.get("type") == "get_session_stats":
        emit(
            {
                "type": "response",
                "command": "get_session_stats",
                "id": command.get("id"),
                "success": True,
                "data": {"tokens": {"input": 0, "output": 0, "total": 0}},
            }
        )
    elif command.get("type") == "get_state":
        emit(
            {
                "type": "response",
                "command": "get_state",
                "id": command.get("id"),
                "success": True,
                "data": {},
            }
        )
    elif command.get("type") == "prompt":
        emit(
            {
                "type": "response",
                "command": "prompt",
                "id": command.get("id"),
                "success": True,
                "data": {"disposition": "started"},
            }
        )
        emit(
            {
                "type": "extension_ui_request",
                "id": "status-1",
                "method": "setStatus",
                "statusKey": "blackhole",
                "statusText": "x" * (80 * 1024),
            }
        )
        emit({"type": "agent_start"})
        emit({"type": "turn_start"})
        system_message = {
            "role": "system",
            "content": "",
            "sections": {"preamble": "x" * (80 * 1024)},
        }
        emit({"type": "message_start", "message": system_message})
        emit({"type": "message_end", "message": system_message})
        emit(
            {
                "type": "message_start",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": command.get("message", "")}],
                },
            }
        )
        emit(
            {
                "type": "message_end",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": command.get("message", "")}],
                },
            }
        )
        assistant = {
            "role": "assistant",
            "content": [{"type": "text", "text": "READY"}],
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
        }
        emit({"type": "message_end", "message": assistant})
        emit({"type": "turn_end", "message": assistant})
        emit({"type": "agent_end", "messages": [system_message, assistant]})
        emit({"type": "agent_settled", "aborted": False})

#!/usr/bin/env python3
"""Small Pi RPC JSONL fake for adapter tests."""

import json
import os
import sys

API_ERROR = (
    '401: {"type":"authentication_error","code":"api_key_expired",'
    '"message":"This API key has expired. Create a new API key in OpenCode '
    "Console and replace it in your client or secret store. Signing in again "
    'will not renew this key."}'
)


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log(value):
    path = os.environ.get("FAKE_PI_LOG")
    if path:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(value) + "\n")


def respond(command, *, data=None):
    response = {
        "type": "response",
        "command": command.get("type"),
        "id": command.get("id"),
        "success": True,
    }
    if data is not None:
        response["data"] = data
    emit(response)


pending_dialog_prompt = None
for line in sys.stdin.buffer:
    command = json.loads(line)
    kind = command.get("type")
    log(command)

    if kind == "extension_ui_response" and pending_dialog_prompt:
        respond(pending_dialog_prompt, data={"disposition": "handled"})
        emit({"type": "agent_settled", "aborted": False})
        pending_dialog_prompt = None
    elif kind == "prompt":
        if os.environ.get("FAKE_PI_RPC_FAILURE"):
            emit(
                {
                    "type": "response",
                    "command": "prompt",
                    "id": command.get("id"),
                    "success": False,
                    "error": API_ERROR,
                }
            )
            continue
        if os.environ.get("FAKE_PI_DIALOG"):
            pending_dialog_prompt = command
            emit(
                {
                    "type": "extension_ui_request",
                    "id": "dialog-1",
                    "method": "confirm",
                    "title": "Confirm action?",
                }
            )
            continue
        respond(command, data={"disposition": "started"})
        if os.environ.get("FAKE_PI_NO_OUTPUT"):
            sys.stderr.write(API_ERROR + "\n")
            sys.stderr.flush()
            continue
        if os.environ.get("FAKE_PI_CLOSE_STDOUT"):
            sys.stderr.write(API_ERROR + "\n")
            sys.stderr.flush()
            sys.stdout.close()
            sys.exit(3)
        emit({"type": "agent_start"})
        if os.environ.get("FAKE_PI_AUTH_ERROR"):
            emit(
                {
                    "type": "message_end",
                    "message": {
                        "role": "assistant",
                        "content": [],
                        "stopReason": "error",
                        "errorMessage": API_ERROR,
                    },
                }
            )
            emit({"type": "agent_end", "messages": []})
            emit({"type": "agent_settled", "aborted": False})
            continue
        if os.environ.get("FAKE_PI_CRASH_PROMPT"):
            sys.exit(3)
        if os.environ.get("FAKE_PI_HOLD_PROMPT"):
            continue
        emit(
            {
                "type": "message_end",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                },
            }
        )
        emit({"type": "agent_settled", "aborted": False})
    elif kind == "get_session_stats":
        if os.environ.get("FAKE_PI_LARGE_FRAME"):
            emit({"type": "extension_error", "error": "x" * 70_000})
        data = {
            "sessionFile": "/fake-pi-session.jsonl",
            "tokens": {"input": 8, "output": 3, "total": 11},
            "cost": 0.02,
        }
        if os.environ.get("FAKE_PI_MISSING_STATS"):
            data.pop("tokens")
        respond(command, data=data)
    elif kind == "abort":
        respond(command)
        emit({"type": "agent_settled", "aborted": True})
    else:
        respond(command, data={"disposition": "queued"})

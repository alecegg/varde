#!/usr/bin/env python3
"""Configurable stream-json peer for ClaudeCliPlugin tests."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def record_launch() -> None:
    path = os.getenv("FAKE_CLAUDE_LOG")
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\n")


def start_child() -> None:
    path = os.getenv("FAKE_CLAUDE_CHILD_PID")
    if not path:
        return
    code = (
        "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "time.sleep(120)"
    )
    child = subprocess.Popen(  # noqa: S603 - fixed test-only grandchild program
        [sys.executable, "-c", code], start_new_session=False
    )
    Path(path).write_text(str(child.pid), encoding="utf-8")


def emit(message: dict) -> None:
    print(json.dumps(message), flush=True)


record_launch()
if os.getenv("FAKE_CLAUDE_LARGE_LINES") == "1":
    print("x" * (1024 * 1024), flush=True)
    print(
        json.dumps(
            {
                "type": "system",
                "subtype": "session_state_changed",
                "state": {"name": "idle"},
            }
        ),
        flush=True,
    )
    print("y" * (1024 * 1024), file=sys.stderr, flush=True)
    print("stderr-followup", file=sys.stderr, flush=True)
    sys.exit(0)
if os.getenv("FAKE_CLAUDE_OVERSIZED_THEN_EVENT") == "1":
    print("x" * (17 * 1024 * 1024), flush=True)
    print(
        json.dumps(
            {
                "type": "system",
                "subtype": "session_state_changed",
                "state": {"name": "idle"},
            }
        ),
        flush=True,
    )
    for _ in sys.stdin:
        pass
    sys.exit(0)
if os.getenv("FAKE_CLAUDE_OVERSIZED_LINES") == "1":
    print("x" * (17 * 1024 * 1024), flush=True)
    print("y" * (17 * 1024 * 1024), file=sys.stderr, flush=True)
    print("stderr-followup", file=sys.stderr, flush=True)
    sys.exit(0)
if os.getenv("FAKE_CLAUDE_IGNORE_TERM") == "1":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
start_child()
if os.getenv("FAKE_CLAUDE_HANG") == "1":
    while True:
        time.sleep(1)
emit(
    {
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "agent": os.getenv("VARDE_AGENT_ID"),
                            "harness": os.getenv("VARDE_HARNESS"),
                            "state_events": os.getenv(
                                "CLAUDE_CODE_EMIT_SESSION_STATE_EVENTS"
                            ),
                            "stripped": all(
                                key not in os.environ
                                for key in (
                                    "ANTHROPIC_API_KEY",
                                    "ANTHROPIC_AUTH_TOKEN",
                                    "CLAUDE_CODE_OAUTH_TOKEN",
                                )
                            ),
                        }
                    ),
                }
            ]
        },
    }
)
emit(
    {
        "type": "control_request",
        "request_id": "permit-1",
        "request": {
            "subtype": "can_use_tool",
            "tool_name": "Bash",
            "tool_use_id": "tool-1",
            "input": {"command": "echo private-input"},
        },
    }
)
if os.getenv("FAKE_CLAUDE_EXIT_IDLE") == "1":
    sys.exit(0)

for line in sys.stdin:
    message = json.loads(line)
    if message["type"] == "user":
        if os.getenv("FAKE_CLAUDE_EXIT_ON_USER") == "1":
            sys.exit(1)
        prompt = message["message"]["content"]
        if prompt == "fail":
            sys.exit(1)
        if prompt == "complete":
            emit(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "result": "finished",
                    "usage": {"input_tokens": 1},
                }
            )
            continue
        emit(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "tool_use",
                            "id": "tool-1",
                            "name": "Bash",
                            "input": {"command": "echo hidden-tool-args"},
                        },
                    ]
                },
            }
        )
    elif message["type"] == "control_response":
        emit(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(message["response"]["response"]),
                        }
                    ]
                },
            }
        )
        emit(
            {
                "type": "system",
                "subtype": "session_state_changed",
                "state": {"name": "running"},
            }
        )
    elif message["type"] == "control_request":
        if os.getenv("FAKE_CLAUDE_INTERRUPT_REFUSE") == "1":
            emit(
                {
                    "type": "control_response",
                    "response": {
                        "subtype": "error",
                        "request_id": message["request_id"],
                    },
                }
            )
        elif os.getenv("FAKE_CLAUDE_INTERRUPT_IGNORE") != "1":
            emit(
                {
                    "type": "system",
                    "subtype": "session_state_changed",
                    "state": {"name": "idle"},
                }
            )
    time.sleep(0.005)

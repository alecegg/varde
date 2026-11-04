#!/usr/bin/env python3
"""Small JSON-RPC app-server peer used by Codex adapter tests."""

import json
import os
import sys
import time
from pathlib import Path

METHODS = [
    "initialize",
    "initialized",
    "thread/start",
    "thread/resume",
    "turn/start",
    "turn/steer",
    "turn/interrupt",
    "account/rateLimits/read",
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
    "item/permissions/requestApproval",
    "item/tool/requestUserInput",
    "serverRequest/resolved",
]
if "--version" in sys.argv:
    print("codex-cli 0.100.0" if os.getenv("FAKE_CODEX_OLD") else "codex-cli 0.162.1")
    raise SystemExit
if "generate-json-schema" in sys.argv:
    if os.getenv("FAKE_CODEX_MISSING_METHOD"):
        METHODS.remove("turn/steer")
    out = Path(sys.argv[sys.argv.index("--out") + 1])
    client_requests = [
        "initialize",
        "thread/start",
        "thread/resume",
        "turn/start",
        "turn/steer",
        "turn/interrupt",
        "account/rateLimits/read",
    ]
    if os.getenv("FAKE_CODEX_MISSING_METHOD"):
        client_requests.remove("turn/steer")
    client_notifications = ["initialized"]
    server_requests = [
        "item/commandExecution/requestApproval",
        "item/fileChange/requestApproval",
        "item/permissions/requestApproval",
        "item/tool/requestUserInput",
    ]
    server_notifications = ["serverRequest/resolved"]
    method_files = {
        "ClientRequest.json": client_requests,
        "ClientNotification.json": client_notifications,
        "ServerRequest.json": server_requests,
        "ServerNotification.json": server_notifications,
    }
    for name, methods in method_files.items():
        (out / name).write_text(
            json.dumps(
                {
                    "oneOf": [
                        {"properties": {"method": {"enum": [method]}}}
                        for method in methods
                    ]
                }
            )
        )
    for name in (
        "codex_app_server_protocol.schemas.json",
        "codex_app_server_protocol.v2.schemas.json",
    ):
        (out / name).write_text(json.dumps({"methods": METHODS}))
    for version, files in {
        "v1": ["InitializeParams.json", "InitializeResponse.json"],
        "v2": ["ThreadStartResponse.json", "TurnStartResponse.json"],
    }.items():
        version_dir = out / version
        version_dir.mkdir()
        for name in files:
            (version_dir / name).write_text(json.dumps({"type": "object"}))
    raise SystemExit
thread_id = "thread-fake"
turn_id = "turn-fake"
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    rid = request.get("id")
    log_path = os.getenv("FAKE_CODEX_LOG")
    if log_path:
        with Path(log_path).open("a", encoding="utf-8") as log:
            log.write(json.dumps(request) + "\n")
    if method == "initialize":
        if os.getenv("FAKE_CODEX_RPC_FAIL") == "initialize":
            error = {"code": -32000, "message": "initialize failed"}
            print(json.dumps({"jsonrpc": "2.0", "id": rid, "error": error}), flush=True)
            continue
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {}}), flush=True)
    elif method in {"thread/start", "thread/resume"}:
        if method == "thread/start" and os.getenv("FAKE_CODEX_RPC_FAIL") == method:
            error = {"code": -32000, "message": "thread start failed"}
            print(json.dumps({"jsonrpc": "2.0", "id": rid, "error": error}), flush=True)
            continue
        if method == "thread/resume" and os.getenv("FAKE_CODEX_RESUME_FAIL"):
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "error": {"code": -32000, "message": "resume failed"},
                    }
                ),
                flush=True,
            )
            continue
        if method == "thread/start" and os.getenv("FAKE_CODEX_COLLISION"):
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "method": "item/commandExecution/requestApproval",
                        "params": {
                            "command": "echo collision",
                            "itemId": "collision-item",
                            "threadId": thread_id,
                            "turnId": turn_id,
                        },
                    }
                ),
                flush=True,
            )
        print(
            json.dumps(
                {"jsonrpc": "2.0", "id": rid, "result": {"thread": {"id": thread_id}}}
            ),
            flush=True,
        )
    elif method in {"turn/start", "turn/steer"}:
        text = request["params"]["input"][0]["text"]
        if text == "malformed":
            print("not-json-" + "x" * 200, flush=True)
        if text == "notify-error":
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "error",
                        "params": {
                            "error": {"message": "provider failed"},
                            "willRetry": True,
                            "threadId": thread_id,
                            "turnId": turn_id,
                        },
                    }
                ),
                flush=True,
            )
        if text == "crash":
            raise SystemExit(1)
        if text in {"reject", "reject-steer"}:
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "error": {"code": -32000, "message": "turn rejected"},
                    }
                ),
                flush=True,
            )
            continue
        if text == "large":
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "item/agentMessage/delta",
                        "params": {
                            "delta": "x"
                            * int(
                                os.getenv(
                                    "FAKE_CODEX_LARGE_BYTES", str(17 * 1024 * 1024)
                                )
                            )
                        },
                    }
                ),
                flush=True,
            )
        if text == "first" and os.getenv("FAKE_CODEX_DELAY_START"):
            time.sleep(0.1)
        if not os.getenv("FAKE_CODEX_NO_TURN_STARTED"):
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "turn/started",
                        "params": {"threadId": thread_id, "turn": {"id": turn_id}},
                    }
                ),
                flush=True,
            )
        if os.getenv("FAKE_CODEX_HANG") == "1":
            print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {}}), flush=True)
            while True:
                time.sleep(1)
        if text == "approval":
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 42,
                        "method": "item/commandExecution/requestApproval",
                        "params": {
                            "command": "echo approval",
                            "itemId": "item-1",
                            "threadId": thread_id,
                            "turnId": turn_id,
                        },
                    }
                ),
                flush=True,
            )
        if text == "question":
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "question-1",
                        "method": "item/tool/requestUserInput",
                        "params": {"questions": [{"question": "Choose"}]},
                    }
                ),
                flush=True,
            )
        if text == "limit":
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "account/rateLimits/updated",
                        "params": {
                            "rateLimits": {
                                "primary": {
                                    "usedPercent": 90,
                                    "windowDurationMins": 300,
                                }
                            }
                        },
                    }
                ),
                flush=True,
            )
        if text not in {"hold", "approval", "question"} and not os.getenv(
            "FAKE_CODEX_NO_TURN_STARTED"
        ):
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "turn/completed",
                        "params": {
                            "turn": {
                                "id": turn_id,
                                "status": os.getenv(
                                    "FAKE_CODEX_COMPLETION_STATUS", "completed"
                                ),
                                "error": {"message": "fake failure"}
                                if os.getenv("FAKE_CODEX_COMPLETION_STATUS") == "failed"
                                else None,
                            }
                        },
                    }
                ),
                flush=True,
            )
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {}}), flush=True)
    elif method == "turn/interrupt":
        print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": {}}), flush=True)
        if not os.getenv("FAKE_CODEX_IGNORE_INTERRUPT"):
            print(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "turn/completed",
                        "params": {"turn": {"id": turn_id, "status": "interrupted"}},
                    }
                ),
                flush=True,
            )
    elif "id" in request and "method" not in request and rid == 42:
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "serverRequest/resolved",
                    "params": {"requestId": 42},
                }
            ),
            flush=True,
        )
        time.sleep(0.1)
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "turn/completed",
                    "params": {"turn": {"id": turn_id, "status": "completed"}},
                }
            ),
            flush=True,
        )
    elif "id" in request and "method" not in request and rid == "question-1":
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "item/agentMessage/delta",
                    "params": {"delta": "question-denied"},
                }
            ),
            flush=True,
        )
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "method": "turn/completed",
                    "params": {"turn": {"id": turn_id, "status": "completed"}},
                }
            ),
            flush=True,
        )
    elif method == "account/rateLimits/read":
        print(
            json.dumps({"jsonrpc": "2.0", "id": rid, "result": {"rateLimits": None}}),
            flush=True,
        )

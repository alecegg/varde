#!/usr/bin/env python3
"""HTTP/SSE fake for OpenCode's subset used by the runner adapter."""

from __future__ import annotations

import base64
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

SPEC_PATH = Path(__file__).parents[1] / "fixtures" / "opencode_2_0_18_subset.json"
SPEC = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
ROUTES = SPEC["paths"]
EVENT_FRAMES = SPEC["event_source"]["frames"]
SESSIONS: dict[str, dict] = {}
LOCK = threading.Lock()
INTERRUPT_EVENT = threading.Event()


class FakeHTTPServer(ThreadingHTTPServer):
    event_connections: int = 0


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _authorized(self) -> bool:
        expected = (
            "Basic "
            + base64.b64encode(
                f"opencode:{os.environ.get('OPENCODE_PASSWORD', '')}".encode()
            ).decode()
        )
        if self.headers.get("Authorization") == expected:
            return True
        self.send_error(401)
        return False

    def _json(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def _record(self, method: str, path: str, body: dict | None = None) -> None:
        log = os.environ.get("FAKE_OPENCODE_LOG")
        if log:
            with open(log, "a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps({"method": method, "path": path, "body": body}) + "\n"
                )

    def _known_route(self, method: str, path: str) -> bool:
        for template, operations in ROUTES.items():
            expected = template.split("/")
            actual = path.split("/")
            if (
                len(expected) == len(actual)
                and all(
                    left == right or (left.startswith("{") and left.endswith("}"))
                    for left, right in zip(expected, actual, strict=True)
                )
                and method.lower() in operations
            ):
                return True
        return False

    def do_GET(self):
        path = urlparse(self.path).path
        if not self._authorized():
            return
        if path not in {"/api/info", "/openapi.json"} and not self._known_route(
            "GET", path
        ):
            self._json(404, {})
            return
        if path == "/api/info":
            self._json(
                200, {"version": os.environ.get("FAKE_OPENCODE_VERSION", "2.0.18")}
            )
            return
        if path == "/openapi.json":
            routes = dict(ROUTES.items())
            if os.environ.get("FAKE_OPENCODE_MISSING_ROUTE"):
                routes.pop("/api/event")
            self._json(
                200, {"paths": routes, "components": {"schemas": SPEC["schemas"]}}
            )
            return
        if path == "/api/event":
            self._record("GET", path)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            sid = next(iter(SESSIONS), "ses_fake")
            server = cast("FakeHTTPServer", self.server)
            server.event_connections += 1
            if (
                os.environ.get("FAKE_OPENCODE_DISCONNECT_ONCE")
                and server.event_connections == 1
            ):
                frame = {"type": "server.connected", "data": {}}
                self.wfile.write(b"data: " + json.dumps(frame).encode() + b"\n\n")
                self.wfile.flush()
                self.close_connection = True
                return
            for source_frame in EVENT_FRAMES:
                if source_frame["type"] == "session.execution.succeeded":
                    continue
                frame = json.loads(
                    json.dumps(source_frame)
                    .replace("ses_fixture", sid)
                    .replace("per_fixture", "per_fake")
                    .replace("frm_fixture", "frm_fake")
                )
                self.wfile.write(b"data: " + json.dumps(frame).encode() + b"\n\n")
                self.wfile.flush()
            if INTERRUPT_EVENT.wait(5):
                frame = {
                    "type": "session.execution.interrupted",
                    "data": {"sessionID": sid, "reason": "user"},
                }
                self.wfile.write(b"data: " + json.dumps(frame).encode() + b"\n\n")
                self.wfile.flush()
            self.close_connection = True
            return
        self._record("GET", path)
        if path.startswith("/api/session/"):
            sid = path.rsplit("/", 1)[-1]
            session = SESSIONS.get(
                sid,
                {"id": sid, "cost": 0.02, "tokens": {"input": 8, "output": 3}},
            )
            self._json(200, {"data": session})
            return
        if path in {"/api/permission/request", "/api/form"}:
            self._json(200, {"data": []})
            return
        self._json(404, {})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if not self._authorized():
            return
        self._record("DELETE", path)
        if self._known_route("DELETE", path):
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self._json(404, {})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self._authorized():
            return
        body = self._body()
        self._record("POST", path, body)
        if not self._known_route("POST", path):
            self._json(404, {})
            return
        if path == "/api/session":
            model_ref = body.get("model")
            required_ref = SPEC["schemas"]["Model.Ref"]["required"]
            if (
                not isinstance(model_ref, dict)
                or any(key not in model_ref for key in required_ref)
                or "modelID" in model_ref
            ):
                self._json(400, {"error": "invalid Model.Ref"})
                return
            required_rule = SPEC["schemas"]["Permission.Rule"]["required"]
            if any(
                not isinstance(rule, dict)
                or any(key not in rule for key in required_rule)
                for rule in body.get("permissions", [])
            ):
                self._json(400, {"error": "invalid Permission.Rule"})
                return
            with LOCK:
                sid = "ses_fake"
                SESSIONS[sid] = {
                    "id": sid,
                    "cost": 0.02,
                    "tokens": {"input": 8, "output": 3},
                }
            self._json(200, {"data": SESSIONS[sid]})
            return
        if path.startswith("/api/session/"):
            if path.endswith("/interrupt"):
                INTERRUPT_EVENT.set()
            self._json(200, {"data": {"ok": True}})
            return
        self._json(404, {})


def main() -> None:
    env_path = os.environ.get("FAKE_OPENCODE_ENV_FILE")
    if env_path:
        names = [
            key
            for key in os.environ
            if "API_KEY" in key.upper()
            or "OAUTH" in key.upper()
            or "ACCESS_TOKEN" in key.upper()
        ]
        Path(env_path).write_text(
            json.dumps(
                {
                    "credential_values": {key: os.environ[key] for key in names},
                    "agent": os.environ.get("VARDE_AGENT_ID"),
                    "harness": os.environ.get("VARDE_HARNESS"),
                    "password": bool(os.environ.get("OPENCODE_PASSWORD")),
                    "xdg_data": os.environ.get("XDG_DATA_HOME"),
                }
            ),
            encoding="utf-8",
        )
    # The adapter passes its selected port on the command line.
    import sys

    port = int(sys.argv[sys.argv.index("--port") + 1])
    server = FakeHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()

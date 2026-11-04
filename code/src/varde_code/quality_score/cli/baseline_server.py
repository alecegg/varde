"""Loopback HTTP server for the baseline page and its JSON API.

Same pattern as ``varde_learn.docs.pages.serve`` (reimplemented: ``code`` and ``doc``
share a level): loopback bind, Host and Origin allowlist, per-run token on POST,
JSON content type check. User code runs only through the sandboxed test runner.
"""

from __future__ import annotations

import hmac
import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from ..baseline_tests import LANGUAGES, toolchain_available
from . import baseline_service as svc
from .baseline_page import Page, build_page

READ_TIMEOUT = 10
TOKEN_HEADER = "X-Varde-Token"  # noqa: S105
NOT_FOUND = "not found"


def allowed_hosts(port: int) -> frozenset[str]:
    return frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})


def allowed_origins(port: int) -> frozenset[str]:
    return frozenset({f"http://127.0.0.1:{port}", f"http://localhost:{port}"})


def is_json_type(content_type: str | None) -> bool:
    if content_type is None:
        return False
    media, _, params = content_type.partition(";")
    if media.strip().lower() != "application/json":
        return False
    return params.strip().lower() in {"", "charset=utf-8"}


def parse_code_request(raw: bytes, with_code: bool = True) -> dict[str, str]:
    """Validate a JSON object of string fields; raise ValueError otherwise."""
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("body must be a JSON object")  # noqa: TRY004
    fields = ("problem", "language", "code") if with_code else ("language",)
    if not all(isinstance(value.get(name), str) for name in fields):
        raise ValueError(f"{', '.join(fields)} must be strings")
    return {name: value[name] for name in fields}


class BaselineServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, data: svc.BaselineData, port: int = 0, debug: bool = False):
        super().__init__(("127.0.0.1", port), BaselineHandler)
        self.data = data
        self.debug = debug
        self.token = secrets.token_urlsafe(32)
        self.hosts = allowed_hosts(self.server_port)
        self.origins = allowed_origins(self.server_port)
        self.page: Page = build_page(self.token, debug)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}/"


class BaselineHandler(BaseHTTPRequestHandler):
    timeout = READ_TIMEOUT

    @property
    def app(self) -> BaselineServer:
        return cast("BaselineServer", self.server)

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send(self, status: int, body: bytes, content_type: str, csp: str = "") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        if csp:
            self.send_header("Content-Security-Policy", csp)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, sort_keys=True).encode()
        self._send(status, body, "application/json")

    def _reject(self, status: HTTPStatus, reason: str) -> None:
        self.close_connection = True
        self._json(status, {"error": reason})

    def _host_ok(self) -> bool:
        if (self.headers.get("Host") or "").lower() in self.app.hosts:
            return True
        self._reject(HTTPStatus.FORBIDDEN, "bad host")
        return False

    # ---- GET ---------------------------------------------------------------

    def do_GET(self) -> None:
        if not self._host_ok():
            return
        parts = urlsplit(self.path)
        try:
            self._get(parts.path, parse_qs(parts.query))
        except Exception:  # noqa: BLE001
            self._reject(HTTPStatus.INTERNAL_SERVER_ERROR, "internal error")

    def _get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/":
            page = self.app.page
            self._send(
                HTTPStatus.OK, page.html.encode(), "text/html; charset=utf-8", page.csp
            )
        elif path == "/api/problems":
            self._json(HTTPStatus.OK, self._problems())
        elif path == "/api/baseline":
            self._baseline(query)
        else:
            self._reject(HTTPStatus.NOT_FOUND, NOT_FOUND)

    def _problems(self) -> dict[str, Any]:
        data = self.app.data
        ids = data.problems()
        return {
            "problems": ids,
            "languages": list(LANGUAGES),
            "statements": {i: data.statement(i) for i in ids},
            "toolchains": {name: toolchain_available(name) for name in LANGUAGES},
        }

    def _baseline(self, query: dict[str, list[str]]) -> None:
        problem = (query.get("problem") or [""])[0]
        language = (query.get("language") or [""])[0]
        data = self.app.data
        if not data.has(problem, language):
            self._reject(HTTPStatus.NOT_FOUND, NOT_FOUND)
            return
        code = data.agreed_code(problem, language)
        calibration, overlay = svc.effective(data, language)
        view = svc.score_code(code, language, calibration, None, self.app.debug)
        self._json(HTTPStatus.OK, {**view, "code": code, "custom": overlay is not None})

    # ---- POST --------------------------------------------------------------

    def do_POST(self) -> None:
        if not self._host_ok():
            return
        path = urlsplit(self.path).path
        if path not in {"/api/score", "/api/save", "/api/reset"}:
            self._reject(HTTPStatus.NOT_FOUND, NOT_FOUND)
            return
        if not self._authorized():
            return
        raw = self._read_body()
        if raw is None:
            return
        try:
            self._post(path, raw)
        except (ValueError, TypeError) as exc:
            self._reject(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception:  # noqa: BLE001
            self._reject(HTTPStatus.INTERNAL_SERVER_ERROR, "internal error")

    def _authorized(self) -> bool:
        if self.headers.get("Origin") not in self.app.origins:
            self._reject(HTTPStatus.FORBIDDEN, "bad origin")
            return False
        if not is_json_type(self.headers.get("Content-Type")):
            self._reject(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "json required")
            return False
        sent = self.headers.get(TOKEN_HEADER) or ""
        if not hmac.compare_digest(sent.encode(), self.app.token.encode()):
            self._reject(HTTPStatus.FORBIDDEN, "bad token")
            return False
        return True

    def _read_body(self) -> bytes | None:
        length = self.headers.get("Content-Length", "")
        if not length.isascii() or not length.isdigit():
            self._reject(HTTPStatus.LENGTH_REQUIRED, "content-length required")
            return None
        if int(length) > svc.MAX_CODE_BYTES:
            self.rfile.read(min(int(length), 4 * svc.MAX_CODE_BYTES))
            self._reject(HTTPStatus.CONTENT_TOO_LARGE, "code too large")
            return None
        return self.rfile.read(int(length))

    def _post(self, path: str, raw: bytes) -> None:
        if path == "/api/reset":
            fields = parse_code_request(raw, with_code=False)
            language = fields["language"]
            if language not in LANGUAGES:
                self._reject(HTTPStatus.BAD_REQUEST, "unknown language")
                return
            self._json(HTTPStatus.OK, {"removed": svc.reset_overlay(language)})
            return
        fields = parse_code_request(raw)
        problem, language, code = fields["problem"], fields["language"], fields["code"]
        if not self.app.data.has(problem, language):
            self._reject(HTTPStatus.NOT_FOUND, NOT_FOUND)
            return
        if len(code.encode()) > svc.MAX_CODE_BYTES:
            self._reject(HTTPStatus.CONTENT_TOO_LARGE, "code too large")
            return
        if path == "/api/score":
            self._score(problem, language, code)
        else:
            self._save(problem, language, code)

    def _score(self, problem: str, language: str, code: str) -> None:
        data = self.app.data
        result = svc.run_behaviour_tests(data, problem, language, code)
        calibration, _ = svc.effective(data, language)
        view = svc.score_code(
            code, language, calibration, svc.tests_state(result), self.app.debug
        )
        if result is not None and not result.ok:
            view["notice"] = "Behaviour tests fail for this code."
        elif result is None:
            view["notice"] = "Tests were not run because the toolchain is missing."
        self._json(HTTPStatus.OK, view)

    def _save(self, problem: str, language: str, code: str) -> None:
        try:
            path, calibration = svc.save_example(self.app.data, problem, language, code)
        except svc.MissingToolchainError:
            self._reject(HTTPStatus.FAILED_DEPENDENCY, "test toolchain missing")
            return
        except svc.TestsFailedError:
            self._reject(HTTPStatus.UNPROCESSABLE_ENTITY, "behaviour tests fail")
            return
        view = svc.score_code(code, language, calibration, True, self.app.debug)
        self._json(HTTPStatus.OK, {**view, "saved": str(path)})

    def _method_not_allowed(self) -> None:
        if self._host_ok():
            self._reject(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _method_not_allowed


def serve(
    data: svc.BaselineData, port: int = 0, debug: bool = False, on_ready: Any = None
) -> None:
    """Serve in the foreground until interrupted."""
    server = BaselineServer(data, port, debug)
    try:
        if on_ready is not None:
            on_ready(server.url)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

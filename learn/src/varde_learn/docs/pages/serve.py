"""Loopback HTTP server for one markdown doc: page, comments, live updates."""

from __future__ import annotations

import hmac
import json
import secrets
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlsplit

from varde_learn.docs.pages.assemble import (
    assemble_page,
)
from varde_learn.docs.pages.comments import (
    KINDS,
    comments_path,
    fold,
    mark_applied,
    read_rows,
)
from varde_learn.docs.pages.edit import (
    EditError,
    accept_replacement,
    apply_edit,
    read_block,
)
from varde_learn.docs.pages.media import Problem, load
from varde_learn.docs.pages.netbind import (
    LOOPBACK,
    allowed_hosts,
    allowed_origins,
    classify_host,
    is_loopback,
)
from varde_learn.docs.pages.remote import (
    edit_denied,
    entry_url,
    handshake_key,
    has_access,
    is_gated_get,
    key_matches,
    set_cookie_header,
)
from varde_learn.docs.pages.template import static_css, static_scripts

STATIC_DIR = Path(__file__).parent / "static"


def _static_body(name: str) -> bytes:
    if name == "app.css":
        return static_css().encode("utf-8")
    return (STATIC_DIR / name).read_bytes()


STATIC_TYPES = {
    **dict.fromkeys(static_scripts(), "text/javascript; charset=utf-8"),
    "app.css": "text/css; charset=utf-8",
}
ACTOR = "user"  # the page user; recorded as the actor that applied a suggestion
EDIT_OFF = "editing is off; serve with --allow-edit"
MAX_BODY = 64 * 1024
MAX_TEXT = 8000
MAX_QUOTE = 200
POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 15
MAX_STREAMS = 16
READ_TIMEOUT = 10
TOKEN_HEADER = "X-Varde-Token"  # noqa: S105
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def is_json_type(content_type: str | None) -> bool:
    if content_type is None:
        return False
    media, _, params = content_type.partition(";")
    if media.strip().lower() != "application/json":
        return False
    return params.strip().lower() in {"", "charset=utf-8"}


def parse_json_object(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError("body is not valid JSON") from error
    if not isinstance(data, dict):
        raise ValueError("body must be a JSON object")  # noqa: TRY004
    return data


def _strings(data: dict[str, Any], *names: str) -> list[str]:
    values = [data.get(name) for name in names]
    if not all(isinstance(value, str) for value in values):
        raise ValueError(f"{' and '.join(names)} must be strings")
    return cast("list[str]", values)


def parse_comment_body(raw: bytes) -> tuple[str, str, str]:
    """Return (anchor, quote, text) or raise ValueError with a short reason."""
    anchor, quote, text, _, _ = parse_comment_fields(raw)
    return anchor, quote, text


def parse_comment_fields(raw: bytes) -> tuple[str, str, str, str, str]:
    """Return (anchor, quote, text, kind, replacement); raise ValueError."""
    return comment_fields(parse_json_object(raw))


def comment_fields(data: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """`parse_comment_fields` for a body that is already parsed."""
    if data.get("kind") in {"suggestion", "drift", "decision", "answer"}:
        data = {"text": "", **data}
    anchor, text = _strings(data, "anchor", "text")
    quote = data.get("quote")
    if quote is None:
        quote = ""
    if not isinstance(quote, str):
        raise ValueError("quote must be a string")  # noqa: TRY004
    kind = data.get("kind", "comment")
    if kind not in KINDS:
        raise ValueError("kind must be comment, suggestion, drift, decision or answer")
    replacement = data.get("replacement", "")
    if not isinstance(replacement, str):
        raise ValueError("replacement must be a string")  # noqa: TRY004
    if max(len(text), len(replacement)) > MAX_TEXT:
        raise ValueError(f"text longer than {MAX_TEXT} characters")
    if kind == "suggestion" and not (quote and len(quote) <= MAX_QUOTE):
        raise ValueError(f"suggestion needs a quote of 1-{MAX_QUOTE} characters")
    return (
        anchor,
        (quote if kind == "suggestion" else quote[:MAX_QUOTE]),
        text,
        kind,
        replacement,
    )


DRIFT_VERDICTS = ("accepted", "rejected", "open")
MAX_ITEM = 600


def parse_drift_fields(raw: bytes) -> tuple[str, str]:
    """Return (item, verdict) of a drift judgment or raise ValueError."""
    return drift_fields(parse_json_object(raw))


def drift_fields(data: dict[str, Any]) -> tuple[str, str]:
    """`parse_drift_fields` for a body that is already parsed."""
    item, verdict = _strings(data, "item", "verdict")
    if not item or len(item) > MAX_ITEM:
        raise ValueError(f"drift item needs 1-{MAX_ITEM} characters")
    if verdict not in DRIFT_VERDICTS:
        raise ValueError("verdict must be accepted, rejected or open")
    return item, verdict


def parse_decision_fields(raw: bytes) -> tuple[str, str]:
    """Return (item, verdict) of a decision answer or raise ValueError."""
    item, verdict = _strings(parse_json_object(raw), "item", "verdict")
    if not item or len(item) > MAX_ITEM:
        raise ValueError(f"decision item needs 1-{MAX_ITEM} characters")
    return item, verdict


def parse_edit_body(raw: bytes) -> tuple[str, str, str]:
    """Return (anchor, base_hash, new_source) or raise ValueError."""
    data = parse_json_object(raw)
    anchor, base_hash, new_source = _strings(data, "anchor", "base_hash", "new_source")
    return anchor, base_hash, new_source


def parse_accept_body(raw: bytes) -> tuple[str, str]:
    """Return (comment_id, base_hash) or raise ValueError."""
    comment_id, base_hash = _strings(parse_json_object(raw), "comment_id", "base_hash")
    return comment_id, base_hash


def render_document(doc: Path, token: str) -> str:
    return assemble_page(doc, token=token)


class Broadcaster:
    """Version counter that SSE handlers wait on; stop wakes them all."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._version = 0
        self._stopped = False

    @property
    def version(self) -> int:
        with self._cond:
            return self._version

    def publish(self) -> None:
        with self._cond:
            self._version += 1
            self._cond.notify_all()

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()

    def wait(self, seen: int, timeout: float) -> tuple[int, bool]:
        """Wait for a version past `seen`; return (version, stopped)."""
        with self._cond:
            self._cond.wait_for(lambda: self._stopped or self._version != seen, timeout)
            return self._version, self._stopped


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


class PageServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        doc: Path,
        port: int = 0,
        host: str = LOOPBACK,
        allow_edit: bool = False,
    ) -> None:
        self.doc = doc
        self.host = classify_host(host)
        self.remote = not is_loopback(self.host)  # tests may override
        self.allow_edit = allow_edit
        self.token = secrets.token_urlsafe(24)
        self.access_key = secrets.token_urlsafe(24)  # printed once; becomes the cookie
        self.broadcaster = Broadcaster()
        self._poller: threading.Thread | None = None
        self._halt = threading.Event()
        self.streams = 0
        self.streams_lock = threading.Lock()
        self.edit_lock = threading.Lock()
        # Test hook: called with (method, path, Host) for every request.
        self.recorder: Callable[[str, str, str], None] | None = None
        super().__init__((self.host, port), PageHandler)
        self.port = self.server_address[1]
        self.hosts = allowed_hosts(self.host, self.port)
        self.origins = allowed_origins(self.host, self.port)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    @property
    def start_url(self) -> str:
        """The URL to print: carries the access key on a non-loopback bind."""
        return entry_url(self.url, self.access_key) if self.remote else self.url

    def _watch_files(self) -> None:
        def current() -> tuple[object, object]:
            return _signature(self.doc), _signature(comments_path(self.doc))

        seen = current()
        while not self._halt.wait(POLL_SECONDS):
            latest = current()
            if latest != seen:
                seen = latest
                self.broadcaster.publish()

    def serve_forever(self, poll_interval: float = 0.5) -> None:
        self._poller = threading.Thread(target=self._watch_files, daemon=True)
        self._poller.start()
        try:
            super().serve_forever(poll_interval)
        finally:
            self._halt.set()
            self.broadcaster.stop()

    def shutdown(self) -> None:
        self._halt.set()
        self.broadcaster.stop()
        super().shutdown()


class PageHandler(BaseHTTPRequestHandler):
    timeout = READ_TIMEOUT  # socket timeout: stalled clients free their thread
    header_override: dict[str, str] | None = None

    @property
    def app(self) -> PageServer:
        return cast("PageServer", self.server)

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def end_headers(self) -> None:
        for name, value in (self.header_override or SECURITY_HEADERS).items():
            self.send_header(name, value)
        self.header_override = None
        super().end_headers()

    def _record(self) -> None:
        if self.app.recorder is not None:
            host = self.headers.get("Host") or ""
            self.app.recorder(self.command, self.path, host)

    def _reply(
        self,
        status: int,
        body: bytes,
        content_type: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Send a reply; `headers` replaces the parent page's security headers."""
        self.header_override = headers
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reject(self, status: HTTPStatus, reason: str) -> None:
        self.close_connection = True
        self._reply(status, reason.encode(), "text/plain; charset=utf-8")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        if host in self.app.hosts:
            return True
        self._reject(HTTPStatus.FORBIDDEN, "bad host")
        return False

    def do_GET(self) -> None:
        self._record()
        if not self._host_ok():
            return
        path = urlsplit(self.path).path
        if self.app.remote and not self._remote_get_ok(path):
            return
        if path == "/events":
            self._stream_events()
            return
        try:
            self._get_content(path)
        except Exception:  # noqa: BLE001
            self._reject(HTTPStatus.INTERNAL_SERVER_ERROR, "internal error")

    def _has_access(self) -> bool:
        return has_access(
            self.headers.get("Cookie"), self.app.access_key, self.app.port
        )

    def _remote_get_ok(self, path: str) -> bool:
        """Handshake a `?k=` entry, else require the cookie on gated routes."""
        sent = handshake_key(self.path)
        if sent is not None:
            self._handshake(sent)
            return False
        if is_gated_get(path) and not self._has_access():
            self._reject(HTTPStatus.FORBIDDEN, "access key required")
            return False
        return True

    def _handshake(self, sent: str) -> None:
        if not key_matches(sent, self.app.access_key):
            self._reject(HTTPStatus.FORBIDDEN, "bad access key")
            return
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie", set_cookie_header(self.app.access_key, self.app.port)
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _get_content(self, path: str) -> None:
        if path == "/":
            self._send_page()
            return
        name = path.removeprefix("/static/") if path.startswith("/static/") else None
        if name in STATIC_TYPES:
            body = _static_body(name)
            self._reply(HTTPStatus.OK, body, STATIC_TYPES[name])
            return
        if path == "/block":
            self._send_block(urlsplit(self.path).query)
            return
        if path.startswith("/media/"):
            self._send_media(unquote(path.removeprefix("/media/")))
            return
        self._reject(HTTPStatus.NOT_FOUND, "not found")

    def _send_media(self, src: str) -> None:
        """An image file under the page's directory; anything else is a 404."""
        found = load(src, self.app.doc.parent)
        if isinstance(found, Problem):
            self._reject(HTTPStatus.NOT_FOUND, "not found")
            return
        self._reply(HTTPStatus.OK, found[0], found[1])

    def _send_page(self) -> None:
        page = render_document(self.app.doc, self.app.token)
        self._reply(HTTPStatus.OK, page.encode(), "text/html; charset=utf-8")

    def _stream_events(self) -> None:
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in {
            "same-origin",
            "none",
        }:
            self._reject(HTTPStatus.FORBIDDEN, "cross-site")
            return
        with self.app.streams_lock:
            if self.app.streams >= MAX_STREAMS:
                self._reject(HTTPStatus.SERVICE_UNAVAILABLE, "too many streams")
                return
            self.app.streams += 1
        try:
            self._send_stream()
        finally:
            with self.app.streams_lock:
                self.app.streams -= 1

    def _send_stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        broadcaster = self.app.broadcaster
        seen = broadcaster.version
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                version, stopped = broadcaster.wait(seen, HEARTBEAT_SECONDS)
                if stopped:
                    return
                message = (
                    b"event: update\ndata: {}\n\n" if version != seen else b": ping\n\n"
                )
                seen = version
                self.wfile.write(message)
                self.wfile.flush()
        except OSError:
            return

    def do_POST(self) -> None:
        self._record()
        if not self._host_ok():
            return
        path = urlsplit(self.path).path
        if self.app.remote and not self._has_access():
            self._reject(HTTPStatus.FORBIDDEN, "access key required")
            return
        handler = self._post_routes().get(path)
        if handler is None:
            self._reject(HTTPStatus.NOT_FOUND, "not found")
            return
        if self.headers.get("Origin") not in self.app.origins:
            self._reject(HTTPStatus.FORBIDDEN, "bad origin")
            return
        if not is_json_type(self.headers.get("Content-Type")):
            self._reject(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "json required")
            return
        sent = self.headers.get(TOKEN_HEADER) or ""
        if not hmac.compare_digest(sent.encode(), self.app.token.encode()):
            self._reject(HTTPStatus.FORBIDDEN, "bad token")
            return
        if edit_denied(path, self.app.remote, self.app.allow_edit):
            self._reject(HTTPStatus.FORBIDDEN, EDIT_OFF)
            return
        raw = self._read_body()
        if raw is not None:
            handler(raw)

    def _post_routes(self) -> dict[str, Callable[[bytes], None]]:
        return {
            "/comments": self._store_comment,
            "/edit": self._store_edit,
            "/accept": self._accept_suggestion,
        }

    def _read_body(self) -> bytes | None:
        length = self.headers.get("Content-Length", "")
        if not length.isascii() or not length.isdigit():
            self._reject(HTTPStatus.LENGTH_REQUIRED, "content-length required")
            return None
        if int(length) > MAX_BODY:
            # Drain a modest body so the client reads the 413, not a reset.
            self.rfile.read(min(int(length), 4 * MAX_BODY))
            self._reject(HTTPStatus.CONTENT_TOO_LARGE, "body too large")
            return None
        return self.rfile.read(int(length))

    def _store_comment(self, raw: bytes) -> None:
        from varde_learn.docs.pages.store import (
            DecisionDenied,
            sources_for,
            store_comment,
        )

        # An answer is gated like a page edit, on top of the cookie.
        decisions_open = not edit_denied("/edit", self.app.remote, self.app.allow_edit)
        try:
            sources = sources_for(self.app.doc, raw)
            row = store_comment(
                self.app.doc, raw, decisions_open=decisions_open, sources=sources
            )
        except DecisionDenied:
            self._reject(HTTPStatus.FORBIDDEN, EDIT_OFF)
            return
        except ValueError as error:
            self._reject(HTTPStatus.BAD_REQUEST, str(error))
            return
        body = json.dumps({"id": row["id"]}).encode()
        self._reply(HTTPStatus.CREATED, body, "application/json")

    def _store_edit(self, raw: bytes) -> None:
        try:
            anchor, base_hash, new_source = parse_edit_body(raw)
            apply_edit(self.app.doc, self.app.edit_lock, anchor, base_hash, new_source)
        except ValueError as error:
            self._reject(HTTPStatus.BAD_REQUEST, str(error))
            return
        except EditError as error:
            self._reject(HTTPStatus(error.status), str(error))
            return
        self.app.broadcaster.publish()
        self._reply(HTTPStatus.OK, b"{}", "application/json")

    def _accept_suggestion(self, raw: bytes) -> None:
        try:
            comment_id, base_hash = parse_accept_body(raw)
            found = [c for c in fold(read_rows(self.app.doc)) if c["id"] == comment_id]
            suggestion = found[0] if found else None
            if suggestion is None or suggestion.get("kind") != "suggestion":
                self._reject(HTTPStatus.NOT_FOUND, "unknown suggestion")
                return
            if suggestion.get("state") != "open":
                self._reject(HTTPStatus.CONFLICT, "suggestion already closed")
                return
            accept_replacement(
                self.app.doc,
                self.app.edit_lock,
                suggestion["anchor"],
                base_hash,
                (suggestion.get("quote", ""), suggestion.get("replacement", "")),
                lambda: mark_applied(self.app.doc, comment_id, ACTOR),
            )
        except ValueError as error:
            self._reject(HTTPStatus.BAD_REQUEST, str(error))
            return
        except EditError as error:
            self._reject(HTTPStatus(error.status), str(error))
            return
        self.app.broadcaster.publish()
        self._reply(HTTPStatus.OK, b"{}", "application/json")

    def _send_block(self, query: str) -> None:
        anchor = (parse_qs(query).get("anchor") or [""])[0]
        try:
            found = read_block(self.app.doc, anchor)
        except EditError as error:
            self._reject(HTTPStatus(error.status), str(error))
            return
        body = json.dumps({"hash": found.block.hash, "source": found.source}).encode()
        self._reply(HTTPStatus.OK, body, "application/json")

    def _method_not_allowed(self) -> None:
        self._record()
        if self._host_ok():
            self._reject(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _method_not_allowed


def serve(
    doc: Path,
    port: int = 0,
    on_ready: Any = None,
    host: str = LOOPBACK,
    allow_edit: bool = False,
) -> None:
    """Serve `doc` in the foreground until interrupted."""
    server = PageServer(doc, port, host, allow_edit)
    try:
        if on_ready is not None:
            on_ready(server.start_url)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

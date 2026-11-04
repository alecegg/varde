from __future__ import annotations

import http.client
import json
import socket
import threading
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from varde_learn.docs.pages import serve as serve_mod
from varde_learn.docs.pages.comments import append_reply, comments_path, fold, read_rows
from varde_learn.docs.pages.serve import PageServer

DOC = "---\nstatus: todo\n---\n\n# Title\n\nHello **world**.\n\n## Part\n\nSecond.\n"
REQUIRED_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; script-src 'self'; "
        "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


class Running:
    def __init__(self, server: PageServer, doc: Path) -> None:
        self.server, self.doc = server, doc
        self.port, self.token = server.port, server.token
        self.host = f"127.0.0.1:{self.port}"

    def request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        merged = {"Host": self.host, **(headers or {})}
        conn.request(method, path, body=body, headers=merged)
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response.status, dict(response.getheaders()), data

    def post(
        self, payload: object = None, **overrides: str | None
    ) -> tuple[int, bytes]:
        body = json.dumps(
            payload or {"anchor": "title", "quote": "Title", "text": "note"}
        ).encode()
        headers: dict[str, str | None] = {
            "Content-Type": "application/json",
            "Origin": f"http://{self.host}",
            "X-Varde-Token": self.token,
        }
        headers.update(overrides)
        sent = {k: v for k, v in headers.items() if v is not None}
        status, _, data = self.request("POST", "/comments", body, sent)
        return status, data


@pytest.fixture
def running(tmp_path: Path) -> Iterator[Running]:
    doc = tmp_path / "plan.md"
    doc.write_text(DOC, encoding="utf-8")
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Running(server, doc)
    server.shutdown()
    server.server_close()
    thread.join(5)


def assert_security_headers(headers: dict[str, str]) -> None:
    for name, value in REQUIRED_HEADERS.items():
        assert headers.get(name) == value, name


def open_sse(app: Running) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", app.port), timeout=5)
    sock.sendall(f"GET /events HTTP/1.1\r\nHost: {app.host}\r\n\r\n".encode())
    return sock


def read_until(sock: socket.socket, needle: bytes, seconds: float = 5) -> bytes:
    buffer = b""
    deadline = time.monotonic() + seconds
    while needle not in buffer and time.monotonic() < deadline:
        try:
            chunk = sock.recv(4096)
        except TimeoutError:
            continue
        if not chunk:
            break
        buffer += chunk
    return buffer


def test_page_has_headers_token_and_first_party_assets(running: Running) -> None:
    status, headers, body = running.request("GET", "/")
    assert status == 200 and headers["Content-Type"].startswith("text/html")
    assert_security_headers(headers)
    text = body.decode()
    assert f'name="varde-token" content="{running.token}"' in text
    assert '<script src="/static/app.js" defer></script>' in text
    assert '<script src="/static/blocks.js" defer></script>' in text
    assert '<script src="/static/recap.js" defer></script>' in text
    assert text.count("<script") == 4 and " style=" not in text
    assert "Hello <strong>world</strong>" in text


def test_static_assets_and_headers(running: Running) -> None:
    for name, kind in (
        ("app.js", "javascript"),
        ("blocks.js", "javascript"),
        ("recap.js", "javascript"),
        ("app.css", "css"),
    ):
        status, headers, body = running.request("GET", f"/static/{name}")
        assert status == 200 and kind in headers["Content-Type"] and body
        assert_security_headers(headers)


@pytest.mark.parametrize(
    "path",
    [
        "/static/../serve.py",
        "/static/%2e%2e/serve.py",
        "/static/app.js/x",
        "/static//etc/passwd",
        "/static/",
        "/nope",
        "/static/__init__.py",
    ],
)
def test_static_traversal_is_404(running: Running, path: str) -> None:
    status, headers, _ = running.request("GET", path)
    assert status == 404
    assert_security_headers(headers)


def test_events_headers(running: Running) -> None:
    sock = open_sse(running)
    head = read_until(sock, b": connected").decode().lower()
    sock.close()
    assert "200 ok" in head and "text/event-stream" in head
    for name, value in REQUIRED_HEADERS.items():
        assert f"{name.lower()}: {value.lower()}" in head


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1:1", "127.0.0.1", ""])
def test_bad_host_rejected_everywhere(running: Running, host: str) -> None:
    for method, path in (("GET", "/"), ("GET", "/events"), ("GET", "/static/app.js")):
        status, headers, _ = running.request(method, path, headers={"Host": host})
        assert status == 403
        assert_security_headers(headers)
    status, _, _ = running.request(
        "POST",
        "/comments",
        b"{}",
        {
            "Host": host,
            "Content-Type": "application/json",
            "Origin": f"http://{running.host}",
            "X-Varde-Token": running.token,
        },
    )
    assert status == 403
    assert fold(read_rows(running.doc)) == []


def test_localhost_host_and_origin_allowed(running: Running) -> None:
    host = f"localhost:{running.port}"
    status, _, _ = running.request("GET", "/", headers={"Host": host})
    assert status == 200
    status, data = running.post(Origin=f"http://{host}")
    assert status == 201, data


def test_comment_appended(running: Running) -> None:
    status, data = running.post(
        {"anchor": "part/1", "quote": "Second.", "text": "why?"}
    )
    assert status == 201
    comments = fold(read_rows(running.doc))
    assert len(comments) == 1 and comments[0]["id"] == json.loads(data)["id"]
    assert comments[0]["anchor"] == "part/1" and comments[0]["text"] == "why?"
    page = running.request("GET", "/")[2].decode()
    assert "why?" in page and 'data-anchor="part/1"' in page


def test_comment_text_is_escaped_in_page(running: Running) -> None:
    running.post({"anchor": "title", "quote": "", "text": "<script>alert(1)</script>"})
    page = running.request("GET", "/")[2].decode()
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page


@pytest.mark.parametrize(
    ("overrides", "status"),
    [
        ({"X-Varde-Token": None}, 403),
        ({"X-Varde-Token": "wrong"}, 403),
        ({"Content-Type": "text/plain"}, 415),
        ({"Content-Type": None}, 415),
        ({"Origin": "http://evil.example"}, 403),
        ({"Origin": None}, 403),
        ({"Origin": "http://127.0.0.1:1"}, 403),
    ],
)
def test_post_rejections(running: Running, overrides: dict, status: int) -> None:
    got, _ = running.post(**overrides)
    assert got == status
    assert fold(read_rows(running.doc)) == []


def test_post_oversize_and_bad_payloads(running: Running) -> None:
    big = {"anchor": "title", "quote": "", "text": "x" * 70_000}
    assert running.post(big)[0] == 413
    assert running.post({"anchor": "title", "quote": "", "text": "x" * 8001})[0] == 400
    assert running.post({"anchor": "Bad Anchor!", "quote": "", "text": "t"})[0] == 400
    assert running.post({"anchor": "title", "quote": "", "text": "  "})[0] == 400
    assert running.post([1, 2])[0] == 400
    status, _, _ = running.request(
        "POST",
        "/comments",
        b"not json",
        {
            "Content-Type": "application/json",
            "Origin": f"http://{running.host}",
            "X-Varde-Token": running.token,
        },
    )
    assert status == 400
    assert fold(read_rows(running.doc)) == []


def test_other_methods_and_paths(running: Running) -> None:
    assert running.request("PUT", "/")[0] == 405
    assert running.request("POST", "/other", b"{}")[0] == 404


def test_sse_event_on_file_change_and_reply(running: Running) -> None:
    sock = open_sse(running)
    read_until(sock, b": connected")
    running.doc.write_text(DOC + "\nMore.\n", encoding="utf-8")
    assert b"event: update" in read_until(sock, b"event: update")
    comment_id = running.post()[1]
    read_until(sock, b"event: update")  # the comment itself also notifies
    time.sleep(0.2)
    append_reply(running.doc, json.loads(comment_id)["id"], "answered")
    assert b"event: update" in read_until(sock, b"event: update")
    sock.close()


def test_heartbeat_sent(running: Running, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(serve_mod, "HEARTBEAT_SECONDS", 0.2)
    sock = open_sse(running)
    assert b": ping" in read_until(sock, b": ping")
    sock.close()


def test_shutdown_within_five_seconds_with_sse_client(tmp_path: Path) -> None:
    doc = tmp_path / "plan.md"
    doc.write_text(DOC, encoding="utf-8")
    server = PageServer(doc, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    app = Running(server, doc)
    sock = open_sse(app)
    read_until(sock, b": connected")
    started = time.monotonic()
    server.shutdown()
    server.server_close()
    thread.join(5)
    assert not thread.is_alive() and time.monotonic() - started < 5
    sock.close()


def test_server_binds_loopback_only(running: Running) -> None:
    assert running.server.server_address[0] == "127.0.0.1"


def test_comments_file_is_beside_doc(running: Running) -> None:
    running.post()
    assert comments_path(running.doc).exists()


def test_built_wheel_contains_static_assets(tmp_path: Path) -> None:
    import shutil
    import subprocess

    root = Path(__file__).resolve().parents[3]
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not available")
    out = tmp_path / "wheels"
    result = subprocess.run(  # noqa: S603
        [
            uv,
            "build",
            "--offline",
            "--wheel",
            "--package",
            "varde-learn",
            "--out-dir",
            str(out),
        ],
        check=False,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    wheel = next(out.glob("varde_learn-*.whl"))
    names = zipfile.ZipFile(wheel).namelist()
    for asset in ("app.js", "css/00-tokens.css", "css/50-blocks.css"):
        assert f"varde_learn/docs/pages/static/{asset}" in names


def test_stalled_post_body_times_out(running: Running, monkeypatch) -> None:
    monkeypatch.setattr(serve_mod.PageHandler, "timeout", 0.5)
    sock = socket.create_connection(("127.0.0.1", running.port), timeout=5)
    sock.sendall(
        (
            f"POST /comments HTTP/1.1\r\nHost: {running.host}\r\n"
            f"Origin: http://{running.host}\r\nContent-Type: application/json\r\n"
            f"X-Varde-Token: {running.token}\r\nContent-Length: 500\r\n\r\n"
        ).encode()
    )
    start = time.monotonic()
    assert sock.recv(4096) == b""  # server gave up and closed
    assert time.monotonic() - start < 4
    sock.close()


def test_sse_connections_are_capped(running: Running, monkeypatch) -> None:
    monkeypatch.setattr(serve_mod, "MAX_STREAMS", 2)
    held = [open_sse(running) for _ in range(2)]
    for sock in held:
        assert b": connected" in read_until(sock, b": connected")
    extra = open_sse(running)
    assert b" 503 " in read_until(extra, b"too many streams")
    for sock in (*held, extra):
        sock.close()


def test_render_error_returns_500(
    running: Running, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(serve_mod, "render_document", boom)
    status, _, body = running.request("GET", "/")
    assert status == 500 and b"internal error" in body


def test_events_rejects_cross_site_fetch(running: Running) -> None:
    status, _, _ = running.request(
        "GET", "/events", headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert status == 403


def _png_bytes() -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + body))
        return struct.pack(">I", len(body)) + kind + body + crc

    header = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
    rows = (b"\x00" + b"\x01\x02\x03" * 2) * 2
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
    )  # fmt: skip


def test_image_route_serves_a_confined_file(running: Running) -> None:
    (running.doc.parent / "a b.png").write_bytes(_png_bytes())
    status, headers, body = running.request("GET", "/media/a%20b.png")
    assert status == 200
    assert headers["Content-Type"] == "image/png"
    assert body == _png_bytes()
    assert_security_headers(headers)


def test_image_route_refuses_everything_else(running: Running) -> None:
    directory = running.doc.parent
    (directory.parent / "out.png").write_bytes(_png_bytes())
    (directory / "text.png").write_text("not an image")
    (directory / ".hid.png").write_bytes(_png_bytes())
    (directory / "note.md").write_text("x")
    (directory / "sub").mkdir()
    (directory / "link.png").symlink_to(directory.parent / "out.png")
    for path in (
        "/media/missing.png",
        "/media/..%2Fout.png",
        "/media/../out.png",
        "/media/%2e%2e/out.png",
        "/media/link.png",
        "/media/text.png",
        "/media/.hid.png",
        "/media/note.md",
        "/media/sub",
        "/media/%2Fetc%2Fhosts.png",
        "/media/",
    ):
        status, _, _ = running.request("GET", path)
        assert status == 404, path


def test_image_page_csp_img_src_is_unchanged(running: Running) -> None:
    status, headers, _ = running.request("GET", "/")
    assert status == 200
    assert "img-src 'self' data:" in headers["Content-Security-Policy"]

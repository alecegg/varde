"""Remote access: access-key handshake, cookie gate and the --allow-edit gate.

The server binds loopback. `remote = True` simulates a non-loopback policy so no
test binds a Tailscale address.
"""

from __future__ import annotations

import http.client
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from varde_learn.docs.pages import remote
from varde_learn.docs.pages.serve import PageServer

DOC = "# Plan\n\nBody text.\n\n```html\n<p>hi</p>\n```\n"


def start(tmp_path: Path, remote_policy: bool, allow_edit: bool = False):
    doc = tmp_path / "plan.md"
    doc.write_text(DOC, encoding="utf-8")
    server = PageServer(doc, 0, "127.0.0.1", allow_edit)
    server.remote = remote_policy
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def stop(server: PageServer, thread: threading.Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(5)


@pytest.fixture
def remote_server(tmp_path: Path) -> Iterator[PageServer]:
    server, thread = start(tmp_path, True)
    yield server
    stop(server, thread)


@pytest.fixture
def editing_server(tmp_path: Path) -> Iterator[PageServer]:
    server, thread = start(tmp_path, True, allow_edit=True)
    yield server
    stop(server, thread)


@pytest.fixture
def loopback_server(tmp_path: Path) -> Iterator[PageServer]:
    server, thread = start(tmp_path, False)
    yield server
    stop(server, thread)


def request(
    srv: PageServer,
    method: str,
    path: str,
    *,
    cookie: bool = False,
    body: dict[str, Any] | None = None,
    token: bool = True,
) -> tuple[int, dict[str, str], bytes]:
    host = f"127.0.0.1:{srv.port}"
    headers = {"Host": host}
    if cookie:
        headers["Cookie"] = f"{remote.cookie_name(srv.port)}={srv.access_key}"
    payload = None
    if method == "POST":
        headers["Origin"] = f"http://{host}"
        headers["Content-Type"] = "application/json"
        if token:
            headers["X-Varde-Token"] = srv.token
        payload = json.dumps(body or {})
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.request(method, path, payload, headers)
    response = conn.getresponse()
    data = response.read() if path != "/events" else b""
    out = (response.status, {k.lower(): v for k, v in response.getheaders()}, data)
    conn.close()
    return out


GATED = [
    ("GET", "/"),
    ("GET", "/events"),
    ("GET", "/block?anchor=x"),
    ("POST", "/comments"),
]


@pytest.mark.parametrize(("method", "path"), GATED)
def test_gated_route_without_cookie_is_403(
    remote_server: PageServer, method: str, path: str
) -> None:
    assert request(remote_server, method, path)[0] == 403


@pytest.mark.parametrize("path", ["/edit", "/accept", "/nowhere"])
def test_every_post_needs_the_cookie(remote_server: PageServer, path: str) -> None:
    assert request(remote_server, "POST", path)[0] == 403


def test_cookie_holder_is_served_and_static_stays_open(
    remote_server: PageServer,
) -> None:
    status, _, body = request(remote_server, "GET", "/", cookie=True)
    assert status == 200
    assert remote_server.token.encode() in body
    assert request(remote_server, "GET", "/static/app.js")[0] == 200


def test_handshake_sets_exact_cookie_and_redirects_to_clean_url(
    remote_server: PageServer,
) -> None:
    status, headers, _ = request(
        remote_server, "GET", f"/?k={remote_server.access_key}"
    )
    assert status == 303
    assert headers["location"] == "/"
    assert "k=" not in headers["location"]
    assert headers["set-cookie"] == (
        f"varde_access_{remote_server.port}={remote_server.access_key}; "
        "HttpOnly; SameSite=Strict; Path=/"
    )


@pytest.mark.parametrize("wrong", ["nope", "", "varde_access"])
def test_wrong_key_is_403_without_cookie(remote_server: PageServer, wrong: str) -> None:
    status, headers, _ = request(remote_server, "GET", f"/?k={wrong}")
    assert status == 403
    assert "set-cookie" not in headers


def test_key_on_other_paths_does_not_handshake(remote_server: PageServer) -> None:
    path = f"/events?k={remote_server.access_key}"
    assert request(remote_server, "GET", path)[0] == 403


def test_start_url_carries_key_only_when_remote(
    remote_server: PageServer, loopback_server: PageServer
) -> None:
    assert (
        remote_server.start_url == f"{remote_server.url}?k={remote_server.access_key}"
    )
    assert loopback_server.start_url == loopback_server.url
    assert remote_server.access_key != remote_server.token


def test_edit_and_accept_are_403_without_allow_edit(remote_server: PageServer) -> None:
    for path in ("/edit", "/accept"):
        status, _, body = request(remote_server, "POST", path, cookie=True, body={})
        assert status == 403
        assert b"--allow-edit" in body
    status, _, _ = request(
        remote_server,
        "POST",
        "/comments",
        cookie=True,
        body={"anchor": "x", "text": "t"},
    )
    assert status == 201


def test_edit_passes_the_gate_with_allow_edit(editing_server: PageServer) -> None:
    status, _, body = request(editing_server, "POST", "/edit", cookie=True, body={})
    assert status == 400
    assert b"--allow-edit" not in body


def test_loopback_needs_no_cookie_and_edit_stays_on(
    loopback_server: PageServer,
) -> None:
    assert request(loopback_server, "GET", "/")[0] == 200
    assert request(loopback_server, "POST", "/edit", body={})[0] == 400
    assert (
        request(loopback_server, "GET", f"/?k={loopback_server.access_key}")[0] == 200
    )


def test_real_non_loopback_default_policy() -> None:
    from varde_learn.docs.pages import netbind

    assert netbind.is_loopback("127.0.0.1")
    assert not netbind.is_loopback("100.64.147.39")


def test_cookie_parsing_ignores_garbage() -> None:
    assert remote.cookie_value(None, 80) == ""
    assert remote.cookie_value("a=b; varde_access_80=xyz; c=d", 80) == "xyz"
    assert remote.cookie_value("\x00bad", 80) == ""
    assert not remote.has_access("varde_access_80=other", "key", 80)
    assert remote.has_access("varde_access_80=key", "key", 80)


def test_cookie_is_scoped_to_its_port() -> None:
    """Another server on the same host (other port) neither shares nor clobbers it."""
    assert remote.cookie_name(8767) != remote.cookie_name(8768)
    assert not remote.has_access("varde_access_8768=key", "key", 8767)
    assert not remote.has_access("varde_access=key", "key", 8767)


def test_edit_denied_rule() -> None:
    assert remote.edit_denied("/edit", True, False)
    assert remote.edit_denied("/accept", True, False)
    assert not remote.edit_denied("/edit", True, True)
    assert not remote.edit_denied("/edit", False, False)
    assert not remote.edit_denied("/comments", True, False)


@pytest.mark.slow
def test_entry_url_sets_the_cookie_in_chromium(
    browser_session: Any, remote_server: PageServer
) -> None:
    calls: list[tuple[str, str, str]] = []
    remote_server.recorder = lambda *call: calls.append(call)
    page = browser_session.new_page()
    page.set_default_timeout(10_000)
    try:
        page.goto(remote_server.start_url)
        assert page.url == remote_server.url
        assert "k=" not in page.url
        page.wait_for_selector("main")
        assert page.evaluate("() => document.cookie") == ""  # HttpOnly
        assert any(c[1] == "/" for c in calls)
    finally:
        page.close()

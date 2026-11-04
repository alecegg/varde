"""Bind address rules: classifier, allowlists, bind refusal and Host/Origin checks."""

from __future__ import annotations

import errno
import http.client
import json
import socket
import threading
from pathlib import Path

import pytest
from varde_learn.docs.pages import cli as pages_cli
from varde_learn.docs.pages import netbind
from varde_learn.docs.pages.serve import PageServer


@pytest.mark.parametrize(
    "host", ["100.64.147.39", "100.64.0.0", "100.127.255.255", "127.0.0.1"]
)
def test_accepted_addresses(host: str) -> None:
    assert netbind.classify_host(host) == host


@pytest.mark.parametrize(
    "host",
    [
        "100.128.0.1",
        "100.63.255.255",
        "0.0.0.0",  # noqa: S104 - asserting this is refused
        "192.168.1.5",
        "8.8.8.8",
        "127.0.0.2",
        "::1",
        "fd7a:115c:a1e0::1",
        "localhost",
        "host.tailnet.ts.net",
        "",
    ],
)
def test_refused_addresses(host: str) -> None:
    with pytest.raises(ValueError, match="host"):
        netbind.classify_host(host)


def test_allowlists_hold_bound_ip_and_loopback_names() -> None:
    assert netbind.allowed_hosts("100.64.147.39", 80) == {
        "100.64.147.39:80",
        "127.0.0.1:80",
        "localhost:80",
    }
    assert "http://100.64.147.39:80" in netbind.allowed_origins("100.64.147.39", 80)


def _unassigned_tailscale_address() -> str:
    """Return an in-range address this machine cannot bind (not a real tailnet one)."""
    for last in range(254, 200, -1):
        candidate = f"100.127.255.{last}"
        with socket.socket() as probe:
            try:
                probe.bind((candidate, 0))
            except OSError as error:
                if error.errno == errno.EADDRNOTAVAIL:
                    return candidate
    pytest.skip("no unassigned in-range address available")


def test_unassigned_in_range_address_fails_with_bind_error(
    tmp_path: Path, capsys
) -> None:
    doc = tmp_path / "plan.md"
    doc.write_text("# P\n", encoding="utf-8")
    code = pages_cli.serve_doc(doc, 0, False, _unassigned_tailscale_address())
    assert code != 0
    assert "not assigned to this machine" in capsys.readouterr().err


def test_refused_host_fails_before_binding(tmp_path: Path, capsys) -> None:
    doc = tmp_path / "plan.md"
    doc.write_text("# P\n", encoding="utf-8")
    assert pages_cli.serve_doc(doc, 0, False, "0.0.0.0") != 0  # noqa: S104
    assert "refused" in capsys.readouterr().err


def test_cli_rejects_bad_host(tmp_path: Path, capsys) -> None:
    from varde_learn.docs.cli import run

    doc = tmp_path / "plan.md"
    doc.write_text("# P\n", encoding="utf-8")
    assert run(["serve", str(doc), "--host", "::1"]) != 0
    assert "IPv6" in capsys.readouterr().err


@pytest.fixture
def server(tmp_path: Path):
    doc = tmp_path / "plan.md"
    doc.write_text("# P\n\ntext\n", encoding="utf-8")
    srv = PageServer(doc, 0, "127.0.0.1")
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(5)


def _get(srv: PageServer, host: str, path: str = "/") -> int:
    conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    conn.putrequest("GET", path, skip_host=True)
    conn.putheader("Host", host)
    conn.endheaders()
    status = conn.getresponse().status
    conn.close()
    return status


def test_host_must_equal_bound_ip_or_loopback_name(server: PageServer) -> None:
    assert _get(server, f"127.0.0.1:{server.port}") == 200
    assert _get(server, f"localhost:{server.port}") == 200
    assert _get(server, f"100.64.147.39:{server.port}") == 403
    assert _get(server, f"me.tailnet.ts.net:{server.port}") == 403
    assert _get(server, f"127.0.0.1:{server.port + 1}") == 403


def test_origin_mismatch_is_403(server: PageServer) -> None:
    body = json.dumps({"anchor": "x", "text": "t"})
    conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
    conn.request(
        "POST",
        "/comments",
        body,
        {
            "Host": f"127.0.0.1:{server.port}",
            "Origin": "http://evil.example",
            "Content-Type": "application/json",
            "X-Varde-Token": server.token,
        },
    )
    assert conn.getresponse().status == 403
    conn.close()
    assert server.url == f"http://127.0.0.1:{server.port}/"
